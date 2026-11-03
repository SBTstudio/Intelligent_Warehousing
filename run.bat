@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem ---------- 0. 检查运行环境 ----------
if not exist ".venv\Scripts\python.exe" (
  echo ============================================================
  echo  [错误] 还没安装运行环境，缺少 .venv 目录。
  echo         请先双击本目录下的「安装环境.bat」，装完再运行本文件。
  echo ============================================================
  echo.
  pause
  exit /b 1
)

rem ---------- 0.1 检查本地大模型服务 ----------
rem 项目依赖 Ollama (127.0.0.1:11434)。没启动就自动拉起托盘程序。
curl -s -o nul --max-time 3 http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
  if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" (
    echo [提示] 本地大模型服务未启动，正在启动 Ollama ...
    start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
    rem 给服务几秒启动时间
    ping -n 5 127.0.0.1 >nul
  ) else (
    echo [警告] 没找到 Ollama，智能推荐功能将走降级模式（统计计算不受影响）
    ping -n 3 127.0.0.1 >nul
  )
)

rem ---------- 1. 启动主程序 ----------
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
  echo.
  echo Program exited with an error. Press any key to close.
  pause >nul
)
