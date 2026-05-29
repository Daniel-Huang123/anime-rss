from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _reload_runtime_paths():
    import src.utils.runtime_paths as runtime_paths

    return importlib.reload(runtime_paths)


def test_data_root_stays_project_root_in_dev(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    mod = _reload_runtime_paths()

    expected = Path(__file__).resolve().parents[1]
    assert mod.APP_ROOT == expected
    assert mod.DATA_ROOT == expected
    assert mod.CONFIG_FILE == expected / "config.yaml"
    assert mod.PENDING_CHECKS_FILE == expected / ".pending_checks.json"


def test_frozen_mode_migrates_legacy_data_without_overwrite(monkeypatch, tmp_path):
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    (legacy_root / "zhuifanji.exe").write_bytes(b"")
    (legacy_root / "config.yaml").write_text("legacy-config", encoding="utf-8")
    (legacy_root / "state.json").write_text('{"legacy": true}', encoding="utf-8")
    (legacy_root / ".cover_cache").mkdir()
    (legacy_root / ".cover_cache" / "old.jpg").write_bytes(b"old")

    appdata = tmp_path / "AppData" / "Roaming"
    roaming_root = appdata / "zhuifanji"
    roaming_root.mkdir(parents=True)
    (roaming_root / "config.yaml").write_text("new-config", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(legacy_root / "zhuifanji.exe"), raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))

    mod = _reload_runtime_paths()

    assert mod.APP_ROOT == legacy_root
    assert mod.DATA_ROOT == roaming_root
    # Existing roaming config must win.
    assert (roaming_root / "config.yaml").read_text(encoding="utf-8") == "new-config"
    # Missing files and dirs should be migrated from legacy root.
    assert (roaming_root / "state.json").read_text(encoding="utf-8") == '{"legacy": true}'
    assert (roaming_root / ".cover_cache" / "old.jpg").read_bytes() == b"old"
