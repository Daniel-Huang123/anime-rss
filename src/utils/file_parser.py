"""番剧文件名解析工具（参考 AutoAnimeMv 的识别逻辑）。

支持的文件名格式：
  [ANi] 因为太怕痛就全点防御力了 - 03 [1080P][CHAS&JPN].mkv
  [ANi] 番剧名 - 03v2 [1080P].mkv
  [kirara] 番剧名 第03话 [1080P].mkv
  番剧名 S01E03.mkv（标准 SxxExx 格式）
  番剧名/Season 1/S01E03.mkv（目录结构）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# 支持的视频扩展名
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".m2ts", ".ts"}
_SKIP_SEGMENTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
    "node_modules",
}

# 需要去除的画质/编码标记
_QUALITY_TAGS = re.compile(
    r"\b(1080[pi]?|720[pi]?|480[pi]?|4[Kk]|2160[pi]?|"
    r"x264|x265|HEVC|AVC|AAC|FLAC|BluRay|BDRip|WEB-DL|"
    r"CHAS?|JPN|CHT|CHS|BIG5|GB|简体|繁体|字幕)\b",
    re.IGNORECASE,
)

# 字幕组括号：[ANi] 《kirara》 ect.
_SUBGROUP_BRACKET = re.compile(r"^\[([^\[\]]+)\]\s*|^《([^《》]+)》\s*")

# 集数识别（优先级从高到低）
_EP_SEXE = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,4})")          # S01E03
_EP_DASH = re.compile(r"(?<![0-9])[-–]\s*(\d{1,4}(?:\.\d)?)\s*(?!\d)")  # - 03
_EP_話  = re.compile(r"第\s*(\d{1,4}(?:\.\d)?)\s*[话話集]")    # 第03话
_EP_EP  = re.compile(r"\b[Ee][Pp]?\.?\s*(\d{1,4})\b")          # EP03

# 年份（去除）
_YEAR = re.compile(r"\b20\d{2}\b")

# 多余符号清理
_CLEAN_BRACKETS = re.compile(r"\[[^\[\]]*\]|（[^（）]*）|\([^()]*\)")
_CLEAN_TRAIL = re.compile(r"[-_\s]+$")
_CLEAN_LEAD  = re.compile(r"^[-_\s]+")


@dataclass
class ParsedAnime:
    """单个视频文件的解析结果。"""
    file_path: Path
    title: str                # 番剧名（清理后）
    episode: str              # 集数字符串，如 "03" / "1.5"
    season: int = 1           # 季度（默认 1）
    subgroup: str = ""        # 字幕组名
    resolution: str = ""      # 画质，如 "1080P"
    is_special: bool = False  # SP / OVA / 特典
    mtime: datetime = field(default_factory=datetime.now)

    @property
    def sort_key(self) -> tuple:
        """用于排序的 key：(季度, 集数数字)"""
        try:
            ep_num = float(self.episode)
        except (ValueError, TypeError):
            ep_num = 0.0
        return (self.season, ep_num)

    @property
    def display_name(self) -> str:
        """S01E03 格式显示名。"""
        try:
            ep_int = int(float(self.episode))
            ep_str = f"{ep_int:02d}"
            if "." in str(self.episode):
                ep_str = self.episode
        except (ValueError, TypeError):
            ep_str = self.episode
        return f"S{self.season:02d}E{ep_str}"

    @property
    def episode_label(self) -> str:
        """人性化显示，如 "第 3 话"。"""
        try:
            ep = float(self.episode)
            if ep == int(ep):
                return f"第 {int(ep):02d} 话"
            return f"第 {ep} 话"
        except (ValueError, TypeError):
            return f"第 {self.episode} 话"


def parse_filename(path: Path) -> ParsedAnime | None:
    """
    解析视频文件路径，返回 ParsedAnime 或 None（非视频文件）。
    """
    if path.suffix.lower() not in VIDEO_EXTS:
        return None

    name = path.stem  # 不含扩展名
    mtime = datetime.fromtimestamp(path.stat().st_mtime) if path.exists() else datetime.now()

    # 1. 提取字幕组
    subgroup = ""
    m = _SUBGROUP_BRACKET.match(name)
    if m:
        subgroup = (m.group(1) or m.group(2) or "").strip()
        name = name[m.end():]

    # 2. 提取画质信息（在去除前先记录）
    resolution = ""
    res_m = re.search(r"\b(1080[pi]?|720[pi]?|480[pi]?|4[Kk]|2160[pi]?)\b", name, re.I)
    if res_m:
        resolution = res_m.group(1).upper()

    # 3. 识别集数
    episode = ""
    season = 1
    is_special = False

    # SxxExx 格式（最优先，说明已经整理过）
    m = _EP_SEXE.search(name)
    if m:
        season = int(m.group(1))
        episode = m.group(2).lstrip("0") or "0"
        name = name[:m.start()] + name[m.end():]
    else:
        # - 03 格式
        m = _EP_DASH.search(name)
        if m:
            episode = m.group(1).lstrip("0") or "0"
            name = name[:m.start()] + name[m.end():]
        else:
            # 第03话
            m = _EP_話.search(name)
            if m:
                episode = m.group(1).lstrip("0") or "0"
                name = name[:m.start()] + name[m.end():]
            else:
                # EP03
                m = _EP_EP.search(name)
                if m:
                    episode = m.group(1).lstrip("0") or "0"
                    name = name[:m.start()] + name[m.end():]

    # 检测 SP/OVA（SP01、SP1 等带编号的也算）
    if re.search(r"\bSP\d*\b|\bOVA\b|\bOAD\b|特典|特別|番外", name, re.I):
        is_special = True
        season = 0

    # 4. 清理番剧名
    name = _YEAR.sub("", name)
    name = _CLEAN_BRACKETS.sub("", name)  # 去掉 [xxx] (xxx) 内容
    name = _QUALITY_TAGS.sub("", name)
    name = re.sub(r"\s{2,}", " ", name)
    name = _CLEAN_TRAIL.sub("", name)
    name = _CLEAN_LEAD.sub("", name)
    # 去掉末尾的 v2 v3 等版本号
    name = re.sub(r"\s*v\d+\s*$", "", name, flags=re.I)
    title = name.strip() or path.parent.name

    return ParsedAnime(
        file_path=path,
        title=title,
        episode=episode if episode else "?",
        season=season,
        subgroup=subgroup,
        resolution=resolution,
        is_special=is_special,
        mtime=mtime,
    )


# ── 目录扫描 ────────────────────────────────────────────────


@dataclass
class AnimeFolder:
    """一部番剧的所有剧集聚合。"""
    title: str
    episodes: list[ParsedAnime] = field(default_factory=list)
    cover_path: Path | None = None
    cover_url: str | None = None   # 从 state.json 中读取

    @property
    def latest_mtime(self) -> datetime:
        if not self.episodes:
            return datetime.min
        return max(e.mtime for e in self.episodes)

    @property
    def episode_count(self) -> int:
        return len(self.episodes)

    @property
    def latest_episode(self) -> ParsedAnime | None:
        if not self.episodes:
            return None
        return max(self.episodes, key=lambda e: (e.season, float(e.episode) if e.episode != "?" else 0))

    def sorted_episodes(self) -> list[ParsedAnime]:
        def sort_key(e: ParsedAnime):
            try:
                return (e.season, float(e.episode))
            except (ValueError, TypeError):
                return (e.season, 0.0)
        return sorted(self.episodes, key=sort_key)


def scan_media_directory(root: Path | str, depth: int = 4) -> list[AnimeFolder]:
    """
    扫描下载目录，识别所有番剧和剧集。
    返回按最近更新时间降序排列的 AnimeFolder 列表。

    策略：
    1. 优先用目录结构推断标题（目录名 = 番剧名）
    2. 从文件名解析集数
    3. 同一目录下的文件归为同一部番剧
    """
    root = Path(root)
    if not root.exists():
        return []

    # 收集所有视频文件
    all_videos: list[Path] = []
    try:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                # 排除过深的路径
                try:
                    rel = p.relative_to(root)
                    segment_names = [str(seg).strip().lower() for seg in rel.parts[:-1]]
                    if any((name.startswith(".") or name in _SKIP_SEGMENTS) for name in segment_names):
                        continue
                    if len(rel.parts) <= depth:
                        all_videos.append(p)
                except ValueError:
                    pass
    except PermissionError:
        pass

    # 按父目录分组
    from collections import defaultdict
    groups: dict[str, list[ParsedAnime]] = defaultdict(list)

    for video in all_videos:
        parsed = parse_filename(video)
        if parsed is None:
            continue

        try:
            rel = video.relative_to(root)
        except ValueError:
            rel = video

        # 目录结构：root/[季度/]番剧名/ep.mkv
        # 用「紧邻视频文件的父目录」作为番剧标题（跨季度自动合并）
        # 例：2026Q2/进击的巨人/ep.mkv  →  folder_title = "进击的巨人"
        #     进击的巨人/ep.mkv          →  folder_title = "进击的巨人"
        anime_dir = video.parent
        folder_title = anime_dir.name

        # 如果父目录是季度文件夹（如 2026Q2）或根目录本身，退为解析标题
        if (anime_dir == root
                or re.match(r"^\d{4}Q\d$", folder_title)
                or re.match(r"^(Season|S)\s*\d+$", folder_title, re.I)):
            folder_title = parsed.title

        parsed.title = folder_title
        groups[folder_title].append(parsed)

    # 构建 AnimeFolder
    folders: list[AnimeFolder] = []
    for folder_title, episodes in groups.items():
        af = AnimeFolder(title=folder_title, episodes=episodes)
        folders.append(af)

    # 按最新更新时间降序
    folders.sort(key=lambda f: f.latest_mtime, reverse=True)
    return folders


def enrich_with_state(folders: list[AnimeFolder]) -> None:
    """
    用 state.json 中的订阅信息补充封面 URL 和标准标题。
    原地修改 folders 列表。
    """
    from src.utils.state import get_all_subscriptions_flat
    subs = get_all_subscriptions_flat()

    # 建立 title → cover_url 映射（模糊匹配）
    title_map: dict[str, dict] = {}
    for s in subs:
        title_map[s["title"]] = s

    for folder in folders:
        # 精确匹配
        if folder.title in title_map:
            sub = title_map[folder.title]
            folder.cover_url = sub.get("cover_url")
        else:
            # 模糊匹配：folder.title 是订阅标题的子串或反之
            for sub_title, sub in title_map.items():
                if sub_title in folder.title or folder.title in sub_title:
                    folder.cover_url = sub.get("cover_url")
                    break
