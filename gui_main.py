"""追番姬 zhuifanji — PyQt6 原生 GUI 入口。

启动方式（在项目根目录下）：
    uv run python gui_main.py
    # 或直接：
    python gui_main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根目录在 sys.path，无论从哪里启动都能找到 src/gui 包
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gui.main import main

if __name__ == "__main__":
    raise SystemExit(main())
