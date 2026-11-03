@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  echo [错误] 请先双击 安装环境.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
rmdir /s /q build dist 2>nul
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed ^
  --name SmartWMS ^
  --icon assets\icon.ico ^
  --add-data "data\sample;data\sample" ^
  --add-data "assets;assets" ^
  --exclude-module pandas ^
  --exclude-module tkinter ^
  main.py
if errorlevel 1 (
  echo [错误] 打包失败
  pause
  exit /b 1
)
echo 完成：dist\SmartWMS.exe
pause
