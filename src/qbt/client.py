"""qBittorrent Web API 封装。

使用 qbittorrent-api 库，提供：
- RSS feed 管理（添加/删除）
- 种子管理（按季度分类删除）
- 连接测试
"""

from __future__ import annotations

import logging
import re
import socket
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import feedparser
import qbittorrentapi

logger = logging.getLogger(__name__)


_EP_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})[Ee](\d{1,4})"),            # S01E08
    re.compile(r"\[(\d{1,4})(?:v\d)?\]"),                 # [08] / [08v2]（桜都等内嵌命名）
    re.compile(r"(?<![0-9])[-–]\s*(\d{1,4}(?:\.\d)?)(?!\d)"),  # - 08
    re.compile(r"第\s*(\d{1,4})\s*[话話集]"),             # 第08话
    re.compile(r"\b[Ee][Pp]?\.?\s*(\d{1,4})\b"),          # EP08
]


def _episode_key(title: str) -> str | None:
    """从标题里抽出集数标识，用于补拉时同集去重（如同集的简繁/简体两版只取一个）。

    抽不出来时返回 None（调用方不去重、全部保留，避免误丢不同集）。
    """
    for i, pat in enumerate(_EP_PATTERNS):
        m = pat.search(title)
        if m:
            if i == 0:  # SxxExx
                return f"{int(m.group(1))}x{int(m.group(2))}"
            try:
                return str(float(m.group(1)))
            except ValueError:
                return m.group(1)
    return None


def _torrent_url_from_entry(entry) -> str:
    """从 feedparser 条目里取真正的 .torrent 链接。

    蜜柑 RSS 的 entry.link 是「剧集详情页」(/Home/Episode/...)，不是种子；真正的
    .torrent 在 <enclosure>（feedparser → entry.enclosures / 带 bittorrent 类型的 links）。
    旧实现误用 entry.link 把页面 URL 喂给 qB，torrents_add 解析失败 → 补拉不到任何集。
    """
    for enc in (entry.get("enclosures") or []):
        if isinstance(enc, dict):
            href = str(enc.get("href", "") or "").strip()
            if href:
                return href
    for link in (entry.get("links") or []):
        if isinstance(link, dict) and link.get("type") == "application/x-bittorrent":
            href = str(link.get("href", "") or "").strip()
            if href:
                return href
    # 兜底：少数源把种子直接放 link/torrentURL
    for key in ("torrentURL", "link"):
        val = str(entry.get(key, "") or "").strip()
        if val.endswith(".torrent") or val.startswith("magnet:"):
            return val
    torrent = entry.get("torrent")
    if isinstance(torrent, dict):
        return str(torrent.get("url", "") or "").strip()
    return ""


def _is_same_or_child_path(path: str, parent: str) -> bool:
    """Case-insensitive path containment check with segment boundary."""
    if not path or not parent:
        return False
    p = path.replace("\\", "/").rstrip("/").lower()
    root = parent.replace("\\", "/").rstrip("/").lower()
    return p == root or p.startswith(root + "/")


class QBTClient:
    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password

    @contextmanager
    def _client(self) -> Generator[qbittorrentapi.Client, None, None]:
        """上下文管理器，自动登录/登出。"""
        client = qbittorrentapi.Client(
            host=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            VERIFY_WEBUI_CERTIFICATE=False,
            REQUESTS_ARGS={"timeout": 10},
        )
        try:
            client.auth_log_in()
            yield client
        finally:
            try:
                client.auth_log_out()
            except Exception:
                pass

    # ── 连接 ──────────────────────────────────────────────

    @staticmethod
    def is_webui_port_open(host: str, port: int, timeout: float = 0.8) -> bool:
        """仅探测 TCP 端口是否可达（不校验账号密码）。"""
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except Exception:
            return False

    def test_connection(self) -> tuple[bool, str]:
        """测试连接，返回 (成功, 消息)。"""
        try:
            with self._client() as c:
                ver = c.app.version
            return True, f"连接成功，qBittorrent {ver}"
        except qbittorrentapi.LoginFailed:
            return False, "登录失败：用户名或密码错误"
        except Exception as e:
            return False, f"连接失败：{e}"

    # ── RSS Feed ───────────────────────────────────────────

    def add_rss_feed(
        self,
        url: str,
        path: str,
        save_path: str = "",
        must_contain: str = "",
        must_not_contain: str = "",
        use_regex: bool = False,
        smart_filter: bool = True,
    ) -> tuple[bool, str]:
        """
        添加 RSS 订阅并同步创建自动下载规则。

        path 格式：'2026Q1/进击的巨人'
        save_path：种子保存目录；为空时 qBittorrent 使用默认路径。
        must_contain / must_not_contain：集数去重过滤（如 must_contain="CHS" 只下简体）。
        use_regex：must_contain / must_not_contain 是否按正则表达式匹配。
        smart_filter：开启后 qBittorrent 自动跳过已下载集数，防同集重复下载。
        返回 (成功, 消息)。
        """
        try:
            with self._client() as c:
                # 1. 添加 RSS feed
                try:
                    c.rss.add_feed(url=url, item_path=path)
                except qbittorrentapi.Conflict409Error:
                    pass   # feed 已存在，继续确保规则存在

                # 2. 创建/更新自动下载规则（规则名与 path 相同）。
                #    规则负责「订阅之后新到的集」自动下载；订阅时已存在的存量集由
                #    subscribe 的 backfill_from_rss 直接补（qB 不会回溯已抓取的文章）。
                rule_def: dict = {
                    "enabled": True,
                    "mustContain": must_contain,
                    "mustNotContain": must_not_contain,
                    "useRegex": use_regex,
                    "episodeFilter": "",
                    "smartFilter": smart_filter,
                    "addPaused": False,
                    "assignedCategory": path,
                    "affectedFeeds": [url],
                }
                if save_path:
                    rule_def["savePath"] = save_path
                c.rss.set_rule(rule_name=path, rule_def=rule_def)

            logger.info("RSS+规则 已添加：%s → %s  savePath=%s", path, url, save_path)
            return True, f"✓ 已添加 RSS：{path}"
        except Exception as e:
            logger.error("添加 RSS 失败 [%s]: %s", path, e)
            return False, f"添加失败：{e}"

    @staticmethod
    def _rss_title_matches(
        title: str,
        must_contain: str = "",
        must_not_contain: str = "",
        use_regex: bool = False,
    ) -> bool:
        if use_regex:
            if must_contain:
                try:
                    if not re.search(must_contain, title, re.IGNORECASE):
                        return False
                except re.error:
                    return False
            if must_not_contain:
                try:
                    if re.search(must_not_contain, title, re.IGNORECASE):
                        return False
                except re.error:
                    return False
            return True

        if must_contain and must_contain not in title:
            return False
        if must_not_contain and must_not_contain in title:
            return False
        return True

    def backfill_from_rss(
        self,
        rss_url: str,
        category: str,
        save_path: str = "",
        must_contain: str = "",
        must_not_contain: str = "",
        use_regex: bool = False,
        max_items: int = 100,
    ) -> tuple[int, str]:
        """
        主动把 RSS 里匹配的存量集数直接加入 qB（qB 自动下载规则对「订阅前已存在的
        文章」不会回溯触发，这里负责补齐存量；新到的集数仍由规则自动下载）。

        默认 max_items=100：补齐当前 feed 里全部匹配集（蜜柑 RSS 一般只列当季，量可控），
        去重交给 qB（同 infohash 不会重复添加）。
        """
        try:
            feed = feedparser.parse(rss_url)
            entries = list(feed.entries or [])
        except Exception as e:
            return 0, f"RSS parse failed: {e}"

        urls: list[str] = []
        seen_eps: set[str] = set()
        for entry in entries:
            title = str(entry.get("title", "") or "")
            if not self._rss_title_matches(
                title,
                must_contain=must_contain,
                must_not_contain=must_not_contain,
                use_regex=use_regex,
            ):
                continue

            # 同集去重：(CHS|简) 可能同时命中「简繁内封」「简体内嵌」两版，每集只取首个。
            ep = _episode_key(title)
            if ep is not None:
                if ep in seen_eps:
                    continue
                seen_eps.add(ep)

            torrent_url = _torrent_url_from_entry(entry)
            if not torrent_url:
                continue

            urls.append(torrent_url)
            if len(urls) >= max(1, int(max_items)):
                break

        if not urls:
            return 0, "No matching RSS entry for backfill"

        try:
            with self._client() as c:
                c.torrents_add(
                    urls=urls,
                    category=category,
                    save_path=save_path or None,
                    is_paused=False,
                )
            return len(urls), f"Backfilled {len(urls)} item(s)"
        except Exception as e:
            return 0, f"Backfill failed: {e}"

    def unsubscribe(
        self,
        feed_path: str,
        save_path: str = "",
        delete_files: bool = True,
    ) -> tuple[bool, str]:
        """
        完整取消订阅：
          1. 删除 RSS feed
          2. 删除对应下载规则（rule_name == feed_path）
          3. 删除 save_path 下的所有种子（可选）
        """
        try:
            with self._client() as c:
                # 1. RSS feed
                try:
                    c.rss.remove_item(item_path=feed_path)
                except Exception:
                    pass  # 可能已不存在

                # 2. 下载规则
                try:
                    c.rss.remove_rule(rule_name=feed_path)
                except Exception:
                    pass

                # 3. 种子：按 category 匹配（add_rss_feed 写入）+ save_path 兜底
                hashes: set[str] = set()

                for t in c.torrents.info(category=feed_path):
                    hashes.add(t.hash)

                if save_path:
                    for t in c.torrents.info():
                        if _is_same_or_child_path(t.save_path, save_path):
                            hashes.add(t.hash)

                deleted = 0
                if hashes:
                    # 有 save_path 时让 qBittorrent 只移除任务（释放文件句柄），
                    # 由 Python 负责删目录；没有 save_path 时才让 qBittorrent 删文件。
                    c.torrents.delete(
                        torrent_hashes=list(hashes),
                        delete_files=(delete_files and not save_path),
                    )
                    deleted = len(hashes)

            # 4. 删除本地目录（qBittorrent 已释放句柄，Python 直接 rmtree）
            dir_removed = False
            if save_path and delete_files:
                sp = Path(save_path)
                if sp.exists():
                    try:
                        shutil.rmtree(sp)
                        dir_removed = True
                        logger.info("已删除目录：%s", sp)
                    except Exception as rm_err:
                        logger.warning("目录删除失败（可能有文件被占用）：%s — %s", sp, rm_err)

            msg = f"✓ 已取消订阅：{feed_path}"
            if deleted:
                msg += f"，删除 {deleted} 个种子"
            if dir_removed:
                msg += "，已清空本地目录"
            logger.info(msg)
            return True, msg
        except Exception as e:
            logger.error("取消订阅失败 [%s]: %s", feed_path, e)
            return False, f"取消订阅失败：{e}"

    def remove_rss_feed(self, path: str) -> tuple[bool, str]:
        """删除 RSS 订阅，path 同 add_rss_feed。"""
        try:
            with self._client() as c:
                c.rss.remove_item(item_path=path)
            return True, f"✓ 已删除 RSS：{path}"
        except Exception as e:
            return False, f"删除失败：{e}"

    def list_rss_feeds(self) -> dict:
        """返回所有 RSS feeds（原始嵌套 dict，与 qBittorrent 结构一致）。"""
        try:
            with self._client() as c:
                return c.rss.items()
        except Exception as e:
            logger.error("获取 RSS 列表失败：%s", e)
            return {}

    def list_rss_rules(self) -> dict:
        """Return RSS auto-downloading rules."""
        try:
            with self._client() as c:
                return c.rss_rules()
        except Exception as e:
            logger.error("鑾峰彇 RSS 瑙勫垯澶辫触锛?s", e)
            return {}

    def remove_rss_folder(self, folder: str) -> tuple[bool, str]:
        """删除整个 RSS 文件夹（季度清理时用）。"""
        try:
            with self._client() as c:
                c.rss.remove_item(item_path=folder)
            return True, f"✓ 已删除 RSS 文件夹：{folder}"
        except Exception as e:
            return False, f"删除文件夹失败：{e}"

    # ── 种子管理 ──────────────────────────────────────────

    def get_torrents_by_tag(self, tag: str) -> list[dict]:
        """按 tag 查找种子列表。"""
        try:
            with self._client() as c:
                torrents = c.torrents.info(tag=tag)
                return [{"hash": t.hash, "name": t.name, "size": t.size} for t in torrents]
        except Exception as e:
            logger.error("查询种子失败：%s", e)
            return []

    def delete_torrents_by_tag(self, tag: str, delete_files: bool = True) -> tuple[int, str]:
        """
        删除带有指定 tag 的所有种子。
        tag 用季度字符串，如 '2026Q1'。
        返回 (删除数量, 消息)。
        """
        try:
            with self._client() as c:
                torrents = c.torrents.info(tag=tag)
                hashes = [t.hash for t in torrents]
                if not hashes:
                    return 0, f"没有找到 tag={tag} 的种子"
                c.torrents.delete(
                    torrent_hashes=hashes,
                    delete_files=delete_files,
                )
            return len(hashes), f"✓ 已删除 {len(hashes)} 个种子（tag={tag}）"
        except Exception as e:
            return 0, f"删除种子失败：{e}"

    def get_torrent_categories(self) -> list[str]:
        """返回所有种子分类列表。"""
        try:
            with self._client() as c:
                return list(c.torrents.categories().keys())
        except Exception:
            return []
