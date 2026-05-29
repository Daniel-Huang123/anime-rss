# anime-rss 开发规范

## 1. 运行与测试

- 所有 Python 相关命令统一使用 `uv`。
- 推荐命令：
  - `uv run python -m pytest tests/ -q`
  - `uv run ruff check <files>`

## 2. 压缩包处理

- 所有压缩包（`.zip` / `.tar.gz` / `.rar` 等）统一使用 **Bandzip** 解压。
- 不使用命令行解压工具（`unzip` / `tar` / `7z`）。

## 3. 打包

- PyInstaller 打包命令：
  - `uv run pyinstaller --noconfirm --clean zhuifanji.spec`
- 产物目录：`dist/zhuifanji`

## 4. 运行时数据目录

- dev 模式：运行时数据仍在项目根目录。
- frozen/exe 模式：运行时数据在 `%APPDATA%\\zhuifanji`。
- 启动时会从旧 exe 目录迁移缺失数据到 `%APPDATA%\\zhuifanji`，不会覆盖已存在数据。
- 运行时数据包括：
  - `config.yaml`
  - `state.json`
  - `watch_history.json`
  - `potplayer_plays.txt`
  - `.mikan_cache.json`
  - `.pending_checks.json`
  - `crash.log`
  - `.cover_cache/`
  - `assets/covers/`

## 5. GUI 线程约定

- 后台任务使用 `gui/qt/workers.py::Worker`（`QThreadPool`）。
- 结果通过 signal 回主线程处理。
- 不在 worker 线程直接操作 Qt 控件。

## 6. 缓存与状态写入

- 封面/番单优先走缓存，网络请求在后台补齐。
- `state.json` 的写入保持串行，避免并发写导致损坏。

## 7. scrapling 兼容

- 当前使用 `scrapling 0.4.x`。
- `Selector` 仅使用 `.css()`（返回列表），不要使用 `.css_first()`。

## 8. 发布约定（自更新依赖）

- 每个桌面版 release 必须上传：
  - `anime-rss-vX.Y.Z-windows-x64.zip`
  - 同名 `.sha256` 文件
