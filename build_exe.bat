@echo off
setlocal

REM Use uv-managed environment for deterministic builds.
REM First-time setup:
REM   uv sync --group dev --group gui

uv run pyinstaller --noconfirm --clean zhuifanji.spec

echo.
echo Build completed. Output: dist\zhuifanji\zhuifanji.exe
