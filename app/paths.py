"""跨平台路径：源码运行与 PyInstaller 打包后都能找到正确目录。

开发时：
    数据 → <项目>/data
    示例 → <项目>/data/sample

打包后：
    可写数据（app.db、缓存）→ 用户数据目录
        Windows  %LOCALAPPDATA%\\SmartWMS
        macOS    ~/Library/Application Support/SmartWMS
        Linux    ~/.local/share/SmartWMS
    只读资源（示例数据、图标）→ PyInstaller 解包目录 sys._MEIPASS
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "SmartWMS"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打出的可执行文件里。"""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """源码运行时的项目根目录。"""
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    """只读资源根目录。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return project_root()


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)


def user_data_dir() -> Path:
    """可写数据目录（打包后不在安装目录里写文件）。"""
    if not is_frozen():
        return project_root() / "data"

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return user_data_dir() / "app.db"


def sample_dir() -> Path:
    return resource_path("data", "sample")


def mpl_cache_dir() -> Path:
    path = user_data_dir() / ".mplcache"
    path.mkdir(parents=True, exist_ok=True)
    return path
