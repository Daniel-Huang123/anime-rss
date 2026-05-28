"""文件名解析单元测试。"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.utils.file_parser import parse_filename, scan_media_directory, ParsedAnime


def _fake_file(name: str, size: int = 1024 * 1024 * 500) -> Path:
    """创建 mock Path 对象（不访问磁盘）。"""
    p = MagicMock(spec=Path)
    p.name = name
    p.stem = Path(name).stem
    p.suffix = Path(name).suffix
    p.__str__ = lambda self: f"/fake/{name}"
    p.exists.return_value = True
    p.stat.return_value = MagicMock(st_mtime=1700000000, st_size=size)
    return p


# ── parse_filename ────────────────────────────────────────

def test_ani_format():
    """[ANi] 番剧名 - 03 [1080P][CHAS&JPN].mkv"""
    p = _fake_file("[ANi] 因为太怕痛就全点防御力了 - 03 [1080P][CHAS&JPN].mkv")
    result = parse_filename(p)
    assert result is not None
    assert result.subgroup == "ANi"
    assert result.episode == "3"
    assert result.resolution == "1080P"
    assert "因为太怕痛" in result.title


def test_sexe_format():
    """标准 S01E05 格式。"""
    p = _fake_file("番剧名 S01E05.mkv")
    result = parse_filename(p)
    assert result is not None
    assert result.season == 1
    assert result.episode == "5"


def test_话_format():
    """第03话格式。"""
    p = _fake_file("[kirara] 番剧名 第03话 [720P].mkv")
    result = parse_filename(p)
    assert result is not None
    assert result.subgroup == "kirara"
    assert result.episode == "3"


def test_float_episode():
    """浮点集数 1.5。"""
    p = _fake_file("[ANi] 番剧名 - 1.5 [1080P].mkv")
    result = parse_filename(p)
    assert result is not None
    assert result.episode == "1.5"


def test_non_video_file():
    """非视频文件返回 None。"""
    p = _fake_file("subtitle.srt")
    result = parse_filename(p)
    assert result is None


def test_sp_ova_detection():
    """SP/OVA 检测为特典，season=0。"""
    p = _fake_file("[ANi] 番剧名 SP01 [1080P].mkv")
    result = parse_filename(p)
    assert result is not None
    assert result.is_special is True
    assert result.season == 0


def test_episode_label():
    """episode_label 格式化。"""
    p = _fake_file("[ANi] 测试 - 03 [1080P].mkv")
    r = parse_filename(p)
    assert r is not None
    assert r.episode_label == "第 03 话"


def test_display_name():
    """display_name 格式。"""
    p = _fake_file("[ANi] 测试 - 12 [1080P].mkv")
    r = parse_filename(p)
    assert r is not None
    assert r.display_name == "S01E12"


# ── scan_media_directory ──────────────────────────────────

def test_scan_empty_dir(tmp_path):
    folders = scan_media_directory(tmp_path)
    assert folders == []


def test_scan_nonexistent(tmp_path):
    folders = scan_media_directory(tmp_path / "nonexistent")
    assert folders == []


def test_scan_groups_by_folder(tmp_path):
    """同一子目录下的文件应归为一部番剧。"""
    anime_dir = tmp_path / "葬送的芙莉莲"
    anime_dir.mkdir()
    for i in range(1, 4):
        (anime_dir / f"[ANi] 葬送的芙莉莲 - {i:02d} [1080P].mkv").write_bytes(b"x" * 100)

    folders = scan_media_directory(tmp_path)
    assert len(folders) == 1
    assert folders[0].title == "葬送的芙莉莲"
    assert folders[0].episode_count == 3


def test_scan_sorted_by_mtime(tmp_path):
    """返回列表按最近更新时间降序。"""
    import time
    for name in ["番剧A", "番剧B", "番剧C"]:
        d = tmp_path / name
        d.mkdir()
        (d / f"{name} - 01.mkv").write_bytes(b"x" * 100)
        time.sleep(0.05)  # 确保 mtime 不同

    folders = scan_media_directory(tmp_path)
    assert len(folders) == 3
    # 最后创建的 C 应排最前
    assert folders[0].title == "番剧C"


def test_parse_filename_strips_quality_tags():
    """画质标签应被清理出标题。"""
    p = _fake_file("[ANi] 蓝色监狱 - 05 [1080P][x265][CHAS].mkv")
    r = parse_filename(p)
    assert r is not None
    assert "1080P" not in r.title
    assert "x265" not in r.title
    assert "CHAS" not in r.title
