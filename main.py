"""智能仓储管理系统 — 程序入口。

启动方式：
    1. Windows 双击项目根目录的 run.bat
    2. macOS / Linux 执行 ./run.sh
    3. 或在终端执行  .venv/bin/python main.py

首次启动会自动在 data/ 下创建 SQLite 数据库；导入示例数据后即可体验
购物篮分析、补货预测、ABC×XYZ 分类和本地模型经营报告。
"""

from __future__ import annotations

import os
import stat
import sys
import sysconfig
from pathlib import Path

# 保证以项目根目录为基准导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _unhide_macos_qt_plugins() -> None:
    """修复 macOS 上 Qt 平台插件被同步/沙箱工具打上 hidden 标志的问题。

    Qt 的 QFactoryLoader 默认跳过隐藏文件，插件被加上 UF_HIDDEN 后会报
    "Could not find the Qt platform plugin"。这里只清掉 hidden 标志，
    不改动其他文件属性；非 macOS 直接跳过。
    """
    if sys.platform != "darwin":
        return
    try:
        if is_frozen():
            plugin_dir = resource_path("PySide6", "Qt", "plugins", "platforms")
        else:
            plugin_dir = (
                Path(sysconfig.get_paths()["purelib"])
                / "PySide6"
                / "Qt"
                / "plugins"
                / "platforms"
            )
        for path in plugin_dir.glob("*.dylib"):
            flags = os.stat(path).st_flags
            if flags & stat.UF_HIDDEN:
                os.chflags(path, flags & ~stat.UF_HIDDEN)
    except Exception:
        # 权限不足或没有插件目录时不影响正常启动
        pass


_unhide_macos_qt_plugins()

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.db import schema
from app.paths import is_frozen, resource_path
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("智能仓储管理系统")
    app.setApplicationDisplayName("智能仓储管理系统")
    app.setOrganizationName("SBTstudio")
    apply_theme(app)

    icon_path = resource_path("assets", "app_icon.svg")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # 建表。重复调用是安全的；首次运行会在 data/ 下生成 app.db
    try:
        schema.init_db()
    except Exception as exc:  # 数据库坏了也要让窗口起来，把原因显示出来
        print(f"[警告] 数据库初始化失败：{exc}", file=sys.stderr)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
