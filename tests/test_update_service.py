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
