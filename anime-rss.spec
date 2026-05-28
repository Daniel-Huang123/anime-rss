# -*- mode: python ; coding: utf-8 -*-
import os as _os
import html as _html_mod
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# stdlib html 包（yuc_wiki.py 函数体内 from html.parser import HTMLParser 是延迟导入，
# PyInstaller 静态分析扫不到，必须手动把整个 html/ 目录打进 _internal）
_html_dir = _os.path.dirname(_html_mod.__file__)
datas = [
    ('app.py', '.'), ('pages', 'pages'), ('src', 'src'), ('config.example.yaml', '.'),
    (_html_dir, 'html'),
]
binaries = []
hiddenimports = []

# ── Streamlit（必须完整收集）────────────────────────────────
tmp_ret = collect_all('streamlit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# ── requests ────────────────────────────────────────────────
tmp_ret = collect_all('requests')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# ── feedparser ──────────────────────────────────────────────
tmp_ret = collect_all('feedparser')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
hiddenimports += ['sgmllib3k']

# ── PyYAML ──────────────────────────────────────────────────
tmp_ret = collect_all('yaml')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# ── qbittorrentapi ──────────────────────────────────────────
tmp_ret = collect_all('qbittorrentapi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# ── scrapling 及其依赖 ───────────────────────────────────────
tmp_ret = collect_all('scrapling')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# scrapling 依赖：browserforge（指纹数据文件必须 collect_data_files）
tmp_ret = collect_all('browserforge')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# scrapling 其他依赖
for pkg in ['cssselect', 'lxml', 'tld', 'w3lib', 'protego',
            'orjson', 'msgspec', 'curl_cffi', 'tenacity',
            'cachetools']:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# ── urllib3 / certifi / charset_normalizer / idna ───────────
for pkg in ['urllib3', 'certifi', 'charset_normalizer', 'idna']:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# ── 其他 Streamlit 运行时依赖 ────────────────────────────────
for pkg in ['anyio', 'starlette', 'uvicorn', 'httptools',
            'watchdog', 'colorama', 'rich', 'markdown_it',
            'mdurl', 'pygments', 'toml', 'packaging',
            'narwhals', 'pydeck']:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# ── 显式 hiddenimports（动态导入、懒加载模块）───────────────
hiddenimports += [
    # feedparser
    'feedparser', 'feedparser.mixin', 'feedparser.encodings',
    'feedparser.namespaces', 'feedparser.namespaces.base',
    'feedparser.namespaces.dc', 'feedparser.namespaces.georss',
    'feedparser.namespaces.itunes', 'feedparser.namespaces.media',
    'feedparser.namespaces.purl', 'feedparser.namespaces.slash',
    'feedparser.namespaces.syndication', 'feedparser.namespaces.wfw',
    'feedparser.parsers', 'feedparser.parsers.loose',
    'feedparser.parsers.strict',
    # qbittorrentapi
    'qbittorrentapi', 'qbittorrentapi.client', 'qbittorrentapi.auth',
    'qbittorrentapi.app', 'qbittorrentapi.rss', 'qbittorrentapi.torrents',
    'qbittorrentapi.transfer', 'qbittorrentapi.log',
    'qbittorrentapi.search', 'qbittorrentapi.sync',
    'qbittorrentapi.definitions', 'qbittorrentapi.exceptions',
    'qbittorrentapi.request', 'qbittorrentapi._attrdict',
    # pyyaml
    'yaml', '_yaml',
    # scrapling
    'scrapling', 'scrapling.fetchers', 'scrapling.parser',
    'scrapling.engines', 'scrapling.engines.static',
    'scrapling.engines.constants', 'scrapling.engines.toolbelt',
    'scrapling.engines._browsers',
    'scrapling.fetchers.requests', 'scrapling.fetchers.chrome',
    'scrapling.fetchers.stealth_chrome',
    # scrapling 依赖的懒加载
    'cssselect', 'lxml', 'lxml.etree', 'lxml.html',
    'lxml.cssselect',
    'orjson', 'msgspec',
    'tld', 'tld.base',
    'w3lib', 'w3lib.url', 'w3lib.html',
    'protego',
    # requests / urllib3
    'requests', 'requests.adapters', 'requests.auth',
    'requests.cookies', 'requests.exceptions', 'requests.models',
    'requests.sessions', 'requests.structures', 'requests.utils',
    'urllib3', 'urllib3.util', 'urllib3.util.retry',
    'urllib3.util.ssl_', 'urllib3.util.url',
    'certifi', 'charset_normalizer', 'idna',
    # concurrent.futures（find_best_rss 中动态 import）
    'concurrent.futures',
    # pkg_resources（scrapling/browserforge 可能用到）
    'pkg_resources',
]

# ── stdlib html 包（feedparser/lxml 动态导入，collect_submodules 确保打进去）
hiddenimports += collect_submodules('html')


a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='anime-rss',
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
    name='anime-rss',
)
