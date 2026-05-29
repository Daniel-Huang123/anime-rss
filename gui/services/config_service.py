from __future__ import annotations

from src.utils.config import load_config, save_config


class ConfigService:
    @staticmethod
    def load() -> dict:
        try:
            return load_config()
        except FileNotFoundError:
            return {
                "qbittorrent": {
                    "host": "127.0.0.1",
                    "port": 8080,
                    "username": "admin",
                    "password": "",
                    "save_path": "",
                },
                "subtitle_priorities": ["ANi", "kirara"],
                "resource_check": {"recent_weeks": 4},
                "cleanup": {"keep_quarters": 2, "delete_files": True},
                "advanced": {"use_mirror": False, "request_delay": 1.0},
                "ui": {"theme": "ios_white", "auto_refresh_enabled": False, "auto_refresh_seconds": 30},
            }

    @staticmethod
    def save(cfg: dict) -> None:
        save_config(cfg)
