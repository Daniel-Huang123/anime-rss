"""Theme system — 3 presets: deep-night / iOS-white / light-pink.

Usage::
    from gui.themes import apply, current, THEMES, SEASON_LABELS

    apply(QApplication.instance(), "night")   # sets app stylesheet
    c = current()                              # color dict for dynamic styles
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QApplication

SEASON_LABELS = {1: "冬季", 2: "春季", 3: "夏季", 4: "秋季"}
SEASON_ICONS  = {1: "❄️",  2: "🌸",  3: "☀️",   4: "🍂"}


def _qss(c: dict) -> str:
    return f"""
QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-family: "Microsoft YaHei UI","PingFang SC","Noto Sans CJK SC",sans-serif;
    font-size: 13px;
}}
QWidget:disabled {{ color: {c['disabled']}; }}

/* ── scrollbar ── */
QScrollBar:vertical {{
    background: {c['surface']}; width: 8px; border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {c['scroll']}; border-radius: 4px; min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {c['surface']}; height: 8px; border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {c['scroll']}; border-radius: 4px; min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── nav ── */
QListWidget#nav {{
    background: {c['nav']}; border: none;
    border-right: 1px solid {c['border']}; outline: none; padding: 8px 0;
}}
QListWidget#nav::item {{
    color: {c['nav_text']}; padding: 12px 20px;
    border-radius: 6px; margin: 2px 8px;
}}
QListWidget#nav::item:hover  {{ background: {c['nav_hover']}; color: {c['text']}; }}
QListWidget#nav::item:selected {{
    background: {c['accent']}; color: #ffffff; font-weight: 600;
}}

/* ── button ── */
QPushButton {{
    background: {c['btn']}; color: {c['btn_text']};
    border: 1px solid {c['border']};
    border-radius: 6px; padding: 6px 14px; min-height: 28px;
}}
QPushButton:hover  {{ background: {c['btn_hover']}; border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['btn_press']}; }}
QPushButton:disabled {{ color: {c['disabled']}; border-color: {c['border']}; background: {c['surface']}; }}

/* ── inputs ── */
QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c['input']}; color: {c['text']};
    border: 1px solid {c['border']}; border-radius: 5px;
    padding: 5px 8px; min-height: 26px;
    selection-background-color: {c['accent']};
    selection-color: #ffffff;
}}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {c['accent']};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background: {c['input']}; color: {c['text']};
    border: 1px solid {c['border']};
    selection-background-color: {c['accent']}; selection-color: #ffffff;
    outline: none;
}}

/* ── table ── */
QTableWidget {{
    background: {c['surface']}; alternate-background-color: {c['alt']};
    gridline-color: {c['border']};
    border: 1px solid {c['border']}; border-radius: 6px;
}}
QTableWidget::item {{ padding: 4px 8px; color: {c['text']}; }}
QTableWidget::item:selected {{ background: {c['accent']}; color: #ffffff; }}
QHeaderView::section {{
    background: {c['header']}; color: {c['subtext']};
    padding: 6px 8px; border: none;
    border-bottom: 1px solid {c['border']}; font-size: 12px;
}}

/* ── group box ── */
QGroupBox {{
    border: 1px solid {c['border']}; border-radius: 8px;
    margin-top: 10px; padding-top: 8px;
    color: {c['text']}; font-size: 13px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
    background: {c['bg']};
}}

/* ── checkbox ── */
QCheckBox {{ spacing: 6px; color: {c['text']}; background: transparent; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {c['border']}; border-radius: 3px;
    background: {c['input']};
}}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}

/* ── dialogs ── */
QDialog   {{ background: {c['surface']}; }}
QMessageBox {{ background: {c['surface']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}
QInputDialog {{ background: {c['surface']}; }}

/* ── list widget ── */
QListWidget {{
    background: {c['surface']}; border: 1px solid {c['border']};
    border-radius: 6px; outline: none;
}}
QListWidget::item {{ padding: 6px 10px; color: {c['text']}; }}
QListWidget::item:hover {{ background: {c['nav_hover']}; }}
QListWidget::item:selected {{ background: {c['accent']}; color: #ffffff; }}

/* ── scroll area ── */
QScrollArea {{ border: none; background: transparent; }}

/* ── progress ── */
QProgressBar {{
    background: {c['btn']}; border: 1px solid {c['border']};
    border-radius: 4px; text-align: center; color: {c['text']};
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}

/* ── tool button ── */
QToolButton {{
    background: {c['btn']}; color: {c['btn_text']};
    border: 1px solid {c['border']};
    border-radius: 6px; padding: 6px 12px; min-height: 28px;
}}
QToolButton:hover {{ background: {c['btn_hover']}; border-color: {c['accent']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* ── menu ── */
QMenu {{
    background: {c['surface']}; border: 1px solid {c['border']};
    border-radius: 6px; padding: 4px 0;
}}
QMenu::item {{ padding: 7px 20px; color: {c['text']}; }}
QMenu::item:selected {{ background: {c['accent']}; color: #ffffff; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 3px 0; }}

/* ── splitter ── */
QSplitter::handle {{ background: {c['border']}; }}

/* ── labels ── */
QLabel {{ color: {c['text']}; background: transparent; }}

/* ── named selectors ── */
QFrame#metric-card {{
    background: {c['card']}; border-radius: 10px;
    border: 1px solid {c['border']};
}}
QLabel#metric-label {{ color: {c['subtext']}; font-size: 12px; border: none; }}
QLabel#metric-value {{
    color: {c['text']}; font-size: 26px; font-weight: 700; border: none;
}}
QLabel#metric-value[warn="true"]  {{ color: {c['warning']}; }}
QLabel#metric-value[warn="false"] {{ color: {c['text']}; }}

QLabel#qbt-status {{
    font-size: 12px;
    background: {c['surface']}; border: 1px solid {c['border']};
    border-radius: 5px; padding: 4px 10px;
}}
QLabel#qbt-status[status="ok"]           {{ color: {c['success']}; }}
QLabel#qbt-status[status="warn"]         {{ color: {c['warning']}; }}
QLabel#qbt-status[status="error"]        {{ color: {c['error']}; }}
QLabel#qbt-status[status="loading"]      {{ color: {c['subtext']}; }}
QLabel#qbt-status[status="unconfigured"] {{ color: {c['warning']}; }}

QLabel#test-status {{ font-size: 12px; }}
QLabel#test-status[status="ok"]    {{ color: {c['success']}; }}
QLabel#test-status[status="error"] {{ color: {c['error']}; }}
QLabel#test-status[status="idle"]  {{ color: {c['subtext']}; }}

QLabel#page-title  {{ font-size: 22px; font-weight: 700; }}
QLabel#section-header {{ font-size: 15px; font-weight: 600; color: {c['subtext']}; }}
QLabel#day-header  {{ font-size: 14px; font-weight: 700; }}
QLabel#hint-text   {{ color: {c['subtext']}; font-size: 11px; }}
QLabel#status-text {{ color: {c['subtext']}; font-size: 12px; }}
QLabel#summary-text[status="ok"]   {{ color: {c['success']}; font-size: 14px; font-weight: 600; }}
QLabel#summary-text[status="warn"] {{ color: {c['warning']}; font-size: 14px; font-weight: 600; }}

QFrame#cover-card {{
    border: 1px solid {c['border']}; border-radius: 8px; background: {c['card']};
}}
QFrame#cover-card:hover {{ border-color: {c['accent']}; }}
QPushButton#cover-btn {{ border: none; padding: 0; background: transparent; }}
QLabel#card-title {{ font-weight: 600; border: none; font-size: 12px; }}
QLabel#card-subtitle {{ color: {c['subtext']}; font-size: 11px; border: none; }}

QFrame#notif-bar {{
    background: {c['card']}; border: 1px solid {c['accent']};
    border-radius: 6px;
}}
QLabel#notif-text {{
    color: {c['text']}; font-size: 12px;
}}

/* ── hot button (red continue-watching) ── */
QPushButton#hot-btn {{
    background: {c['hot']}; color: #ffffff;
    border: none; border-radius: 8px;
    padding: 10px 22px; min-height: 36px;
    font-size: 14px; font-weight: 600;
}}
QPushButton#hot-btn:hover  {{ background: {c['hot_hover']}; }}
QPushButton#hot-btn:pressed {{ background: {c['hot_press']}; }}
QPushButton#hot-btn:disabled {{ background: {c['disabled']}; color: #ffffff; }}

QPushButton#ep-btn {{
    background: {c['hot']}; color: #ffffff;
    border: none; border-radius: 6px;
    padding: 8px 14px; min-height: 32px;
    font-weight: 600;
}}
QPushButton#ep-btn:hover  {{ background: {c['hot_hover']}; }}
QPushButton#ep-btn:pressed {{ background: {c['hot_press']}; }}
QPushButton#ep-btn[watched="true"] {{
    background: {c['btn']}; color: {c['subtext']};
}}
QPushButton#ep-btn[watched="true"]:hover {{ background: {c['btn_hover']}; }}

QFrame#featured-card {{
    background: {c['card']}; border: 1px solid {c['border']};
    border-radius: 10px;
}}
QLabel#featured-title    {{ font-size: 18px; font-weight: 700; color: {c['text']}; }}
QLabel#featured-meta     {{ font-size: 13px; color: {c['subtext']}; }}
QLabel#featured-emphasis {{ font-size: 13px; color: {c['text']}; font-weight: 600; }}

QPushButton#back-btn {{
    background: {c['btn']}; color: {c['text']};
    border: 1px solid {c['border']}; border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton#back-btn:hover {{ background: {c['btn_hover']}; }}

QLabel#ep-size {{ color: {c['subtext']}; font-size: 11px; }}
"""


_NIGHT = dict(
    bg='#0f0f1a',     surface='#181828',  card='#1e1e30',   input='#18182a',
    alt='#1c1c32',    header='#222238',   nav='#13132a',    nav_hover='#222238',
    nav_text='#7878a8', border='#2d2d50',
    text='#e4e4f0',   subtext='#8888aa',
    btn='#222238',    btn_hover='#2c2c50', btn_press='#1a1a35',
    btn_text='#b8b8d8', disabled='#55557a',
    accent='#6244ee', scroll='#404060',
    hot='#e94c5d',    hot_hover='#f25865', hot_press='#c93a4a',
    success='#00c853', warning='#ff9800', error='#ff5252',
)

_WHITE = dict(
    bg='#f2f2f7',     surface='#ffffff',  card='#ffffff',   input='#ffffff',
    alt='#f5f5fa',    header='#f2f2f7',   nav='#f2f2f7',    nav_hover='#e5e5ea',
    nav_text='#6e6e73', border='#c8c8cc',
    text='#1c1c1e',   subtext='#8e8e93',
    btn='#e5e5ea',    btn_hover='#d8d8de', btn_press='#c8c8ce',
    btn_text='#1c1c1e', disabled='#b0b0b8',
    accent='#007aff', scroll='#b0b0b8',
    hot='#ff3b30',    hot_hover='#ff5045', hot_press='#d62b22',
    success='#34c759', warning='#ff9f0a', error='#ff3b30',
)

_PINK = dict(
    bg='#fff5f8',     surface='#fffbfd',  card='#fff0f5',   input='#ffffff',
    alt='#fdf5f8',    header='#fce4ef',   nav='#fce4ef',    nav_hover='#f8d0e0',
    nav_text='#9a6070', border='#f0c8d8',
    text='#2d1a28',   subtext='#9a6878',
    btn='#fce4ef',    btn_hover='#f8c8da', btn_press='#f0b0c8',
    btn_text='#2d1a28', disabled='#c0909a',
    accent='#d05080', scroll='#d8a0b8',
    hot='#e84c75',    hot_hover='#f05a82', hot_press='#c8395f',
    success='#2a8050', warning='#d06020', error='#d03030',
)

THEMES: dict[str, dict] = {
    "night":      {"label": "深夜",   "colors": _NIGHT, "qss": _qss(_NIGHT)},
    "ios_white":  {"label": "iOS 白", "colors": _WHITE, "qss": _qss(_WHITE)},
    "light_pink": {"label": "浅粉",   "colors": _PINK,  "qss": _qss(_PINK)},
}

DEFAULT_THEME = "night"
_current_name: str = DEFAULT_THEME


def current() -> dict:
    """Return color dict for the active theme."""
    return THEMES[_current_name]["colors"]


def current_name() -> str:
    return _current_name


def apply(app: "QApplication", name: str = DEFAULT_THEME) -> None:
    global _current_name
    if name not in THEMES:
        name = DEFAULT_THEME
    _current_name = name
    app.setStyleSheet(THEMES[name]["qss"])


def repolish(widget) -> None:
    """Force a widget to re-evaluate QSS dynamic properties."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
