@echo off
setlocal

REM 先确保已安装 pyinstaller：
REM uv add --dev pyinstaller

pyinstaller --noconfirm --clean zhuifanji.spec

echo.
echo Build completed. Output: dist\zhuifanji\zhuifanji.exe
