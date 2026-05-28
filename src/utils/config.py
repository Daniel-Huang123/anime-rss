"""config.yaml 的读写工具。"""

from typing import Any

import yaml

from src.utils.runtime_paths import CONFIG_FILE


def load_config() -> dict:
    """读取 config.yaml，返回配置字典。"""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"找不到配置文件：{CONFIG_FILE}")
    return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}


def save_config(config: dict) -> None:
    """将配置字典写回 config.yaml。"""
    CONFIG_FILE.write_text(
        yaml.dump(config, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def get(key_path: str, default: Any = None) -> Any:
    """
    用点分路径读取配置值。
    例：get("qbittorrent.host") → "localhost"
    """
    cfg = load_config()
    keys = key_path.split(".")
    for k in keys:
        if isinstance(cfg, dict):
            cfg = cfg.get(k)
        else:
            return default
        if cfg is None:
            return default
    return cfg
