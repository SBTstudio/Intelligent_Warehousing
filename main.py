"""智能仓储管理系统 — 程序入口。

启动方式：
    1. Windows 双击项目根目录的 run.bat
    2. macOS / Linux 执行 ./run.sh
    3. 或在终端执行  .venv/bin/python main.py

首次启动会自动在 data/ 下创建 SQLite 数据库；导入示例数据后即可体验
购物篮分析、补货预测、ABC×XYZ 分类和本地模型经营报告。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 保证以项目根目录为基准导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.db import schema
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("智能仓储管理系统")
    app.setApplicationDisplayName("智能仓储管理系统")
    app.setOrganizationName("SBTstudio")
    apply_theme(app)

    icon_path = Path(__file__).resolve().parent / "assets" / "app_icon.svg"
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
