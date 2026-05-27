"""qBittorrent Web API 封装。

使用 qbittorrent-api 库，提供：
- RSS feed 管理（添加/删除）
- 种子管理（按季度分类删除）
- 连接测试
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import qbittorrentapi

logger = logging.getLogger(__name__)


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
    ) -> tuple[bool, str]:
        """
        添加 RSS 订阅并同步创建自动下载规则。

        path 格式：'2026Q1/进击的巨人'
        save_path：种子保存目录（如 'D:/Anime/2026Q1/进击的巨人'）；
                   为空时 qBittorrent 使用默认保存路径。
        返回 (成功, 消息)。
        """
        try:
            with self._client() as c:
                # 1. 添加 RSS feed
                try:
                    c.rss.add_feed(url=url, item_path=path)
                except qbittorrentapi.Conflict409Error:
                    pass   # feed 已存在，继续确保规则存在

                # 2. 创建/更新自动下载规则（规则名与 path 相同）
                rule_def: dict = {
                    "enabled": True,
                    "mustContain": "",
                    "mustNotContain": "",
                    "useRegex": False,
                    "episodeFilter": "",
                    "smartFilter": False,
                    "addPaused": False,
                    "assignedCategory": "",
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
