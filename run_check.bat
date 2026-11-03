@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PY=C:\Users\awrzs\AppData\Local\Programs\Python\Python312\python.exe
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

"%PY%" tools\check_env.py
echo.
echo 按任意键关闭窗口
pause >nul
