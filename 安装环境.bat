@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   智能仓储管理系统 - 环境安装
echo   首次使用请双击本文件，装完以后再双击 run.bat
echo ============================================================
echo.

rem ---------- 1. 找 Python 3.12 ----------
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"

if not defined PY (
    echo [错误] 没找到 Python 3.12。
    echo        请到 python.org 下载 Python 3.12 安装，安装时务必勾选
    echo        "Add python.exe to PATH"。
    echo.
    pause
    exit /b 1
)

echo [1/4] 使用的解释器：%PY%
"%PY%" --version
echo.

rem ---------- 2. 建虚拟环境 ----------
if exist ".venv\Scripts\python.exe" (
    echo [2/4] 虚拟环境已存在，跳过创建
) else (
    echo [2/4] 创建虚拟环境 .venv ...
    "%PY%" -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
)
echo.

rem ---------- 3. 装依赖 ----------
echo [3/4] 安装依赖（PySide6 较大，约 100MB，请耐心等待）...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo.
    echo [提示] 清华镜像失败，改用官方源重试...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
echo.

rem ---------- 4. 自检 ----------
echo [4/4] 环境自检：
echo.
".venv\Scripts\python.exe" tools\check_env.py

echo.
echo ============================================================
echo   安装结束。若上面自检全绿，双击 run.bat 即可启动程序。
echo   注意：本地大模型需要另外安装 Ollama 并执行 ollama pull qwen3:4b，
echo         没有 Ollama 时程序仍可运行，只是报告页会降级为模板文字。
echo ============================================================
pause
