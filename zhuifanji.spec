# -*- mode: python ; coding: utf-8 -*-
import os as _os
import html as _html_mod
from PyInstaller.utils.hooks import collect_all, collect_data_files

# html.parser 可能被动态导入，需显式打包 stdlib html 与 _markupbase
import _markupbase as _mb_mod

_html_dir = _os.path.dirname(_html_mod.__file__)
_markupbase_file = _mb_mod.__file__

datas = [
    ('config.example.yaml', '.'),
    (_html_dir, 'html'),
    (_markupbase_file, '.'),
]
binaries = []
hiddenimports = []

# Qt 平台插件（Windows 必需）
datas += collect_data_files('PyQt6.Qt6', includes=['plugins/platforms/*'])

# 项目运行时依赖
for pkg in ['requests', 'feedparser', 'yaml', 'qbittorrentapi']:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

for pkg in [
    'cssselect', 'lxml', 'tld', 'w3lib', 'protego',
    'orjson', 'msgspec', 'tenacity', 'cachetools',
    'urllib3', 'certifi',
    'charset_normalizer', 'idna',
]:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

hiddenimports += ['scrapling.parser']


a = Analysis(
    ['gui_main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['patchright', 'playwright', 'undetected_playwright', 'curl_cffi'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='zhuifanji',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='zhuifanji',
)
