@echo off
setlocal

REM 先确保已安装 pyinstaller：
REM uv add --dev pyinstaller

pyinstaller --noconfirm --clean --onedir --windowed --name anime-rss ^
  --add-data "app.py;." ^
  --add-data "pages;pages" ^
  --add-data "config.example.yaml;." ^
  --collect-all streamlit ^
  run_app.py

echo.
echo Build completed. Output: dist\anime-rss\anime-rss.exe

