from gui.services import update_service


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = "json"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_update_check_skips_streamlit_release_and_uses_desktop_asset(monkeypatch):
    desktop_url = "https://github.com/Daniel-Huang123/anime-rss/releases/download/v0.2.0/zhuifanji.exe"

    def fake_get(url, timeout, headers):
        if "anime-season-rss" in url:
            return FakeResponse(
                [
                    {
                        "tag_name": "v9.9.9",
                        "name": "Streamlit release",
                        "body": "streamlit web deploy",
                        "html_url": "https://github.com/Daniel-Huang123/anime-season-rss/releases/tag/v9.9.9",
                        "assets": [],
                    }
                ]
            )
        return FakeResponse(
            [
                {
                    "tag_name": "v0.2.0",
                    "name": "Desktop GUI",
                    "body": "",
                    "html_url": "https://github.com/Daniel-Huang123/anime-rss/releases/tag/v0.2.0",
                    "assets": [
                        {
                            "name": "zhuifanji.exe",
                            "browser_download_url": desktop_url,
                        }
                    ],
                }
            ]
        )

    monkeypatch.setattr(update_service, "REPO_NAMES", ("anime-season-rss", "anime-rss"))
    monkeypatch.setattr(update_service, "current_version", lambda: "0.1.0")
    monkeypatch.setattr(update_service.requests, "get", fake_get)

    result = update_service.check_latest_release()

    assert result["ok"] is True
    assert result["has_update"] is True
    assert result["latest_version"] == "v0.2.0"
    assert result["url"] == desktop_url


def test_update_check_ignores_release_without_desktop_marker(monkeypatch):
    def fake_get(url, timeout, headers):
        return FakeResponse(
            [
                {
                    "tag_name": "v9.9.9",
                    "name": "Streamlit release",
                    "body": "web app",
                    "assets": [{"name": "source.zip", "browser_download_url": "https://example.test/source.zip"}],
                }
            ]
        )

    monkeypatch.setattr(update_service, "REPO_NAMES", ("anime-season-rss",))
    monkeypatch.setattr(update_service, "current_version", lambda: "0.1.0")
    monkeypatch.setattr(update_service.requests, "get", fake_get)

    result = update_service.check_latest_release()

    assert result["ok"] is False
    assert result["reason"] == "anime-season-rss has no desktop GUI release"


def test_find_update_asset_picks_windows_zip_and_sha():
    release = {
        "assets": [
            {"name": "anime-rss-v0.2.0-windows-x64.zip", "browser_download_url": "https://x/z.zip", "size": 1234},
            {"name": "anime-rss-v0.2.0-windows-x64.zip.sha256", "browser_download_url": "https://x/z.sha256", "size": 64},
            {"name": "notes.txt", "browser_download_url": "https://x/n.txt", "size": 10},
        ]
    }
    a = update_service.find_update_asset(release)
    assert a["url"] == "https://x/z.zip"
    assert a["size"] == 1234
    assert a["sha256_url"] == "https://x/z.sha256"


def test_find_update_asset_empty_without_zip():
    assert update_service.find_update_asset({"assets": [{"name": "src.tar.gz", "browser_download_url": "u"}]}) == {}


def test_sha256_of(tmp_path):
    import hashlib

    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world")
    assert update_service.sha256_of(p) == hashlib.sha256(b"hello world").hexdigest()


def test_fetch_expected_sha256_parses_first_token(monkeypatch):
    digest = "a" * 64

    class _R:
        text = f"{digest}  anime-rss-v0.2.0-windows-x64.zip\n"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(update_service.requests, "get", lambda *a, **k: _R())
    assert update_service.fetch_expected_sha256("https://x/z.sha256") == digest


def test_fetch_expected_sha256_rejects_non_hex(monkeypatch):
    class _R:
        text = "not-a-valid-digest filename"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(update_service.requests, "get", lambda *a, **k: _R())
    assert update_service.fetch_expected_sha256("https://x/z.sha256") == ""


def test_build_updater_ps1_has_wait_copy_restart(tmp_path):
    s = update_service._build_updater_ps1(
        4321, tmp_path / "new", tmp_path / "install", tmp_path / "work", "zhuifanji.exe"
    )
    assert "4321" in s
    assert "robocopy" in s and "/E" in s
    assert "zhuifanji.exe" in s
    assert "Get-Process" in s
    assert "zhuifanji_update.log" in s
    assert "-PassThru" in s


def test_find_build_root_and_exe_name(tmp_path):
    root = tmp_path / "new"
    (root / "_internal").mkdir(parents=True)
    (root / "zhuifanji.exe").write_bytes(b"x")
    assert update_service._find_build_root(tmp_path / "new") == root
    assert update_service._exe_name_in(root) == "zhuifanji.exe"


def test_current_version_reads_pyinstaller_bundle_pyproject(tmp_path, monkeypatch):
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    (bundle_root / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    def missing_metadata(name):
        raise RuntimeError("not installed")

    monkeypatch.setattr(update_service.importlib.metadata, "version", missing_metadata)
    monkeypatch.setattr(update_service, "APP_ROOT", tmp_path / "app")
    monkeypatch.setattr(update_service.sys, "_MEIPASS", str(bundle_root), raising=False)

    assert update_service.current_version() == "1.2.3"
