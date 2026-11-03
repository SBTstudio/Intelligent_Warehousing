"""页面基类。

所有功能页面都继承 WorkPage，它提供统一的标题区、说明和内容区。
页面只往 self.body 里塞控件，不重复写边距和标题样式。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.theme import COLORS


class WorkPage(QWidget):
    """功能页面基类：标题 + 说明 + 可伸展的内容区。"""

    def __init__(self, title: str, hint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkPage")
        self.setStyleSheet("QWidget#WorkPage { background: #F5F4EE; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 22)
        outer.setSpacing(6)

        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        outer.addWidget(heading)

        if hint:
            note = QLabel(hint)
            note.setObjectName("PageHint")
            note.setWordWrap(True)
            outer.addWidget(note)

        outer.addSpacing(8)

        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        # 给 body 伸展因子 1：表格、图表才能跟着窗口一起变大
        outer.addLayout(self.body, 1)

    def add_banner(self, text: str) -> QLabel:
        """在标题下方插一条提示条，返回 label 以便后续改文字/隐藏。"""
        banner = QLabel(text)
        banner.setObjectName("Banner")
        banner.setWordWrap(True)
        self.body.addWidget(banner)
        return banner


class TodoPanel(QLabel):
    """开发占位提示（保留给后续迭代，不再在主流程中使用）。"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet(
            f"background: {COLORS['amber_soft']}; color: #633806;"
            "border: 0.5px solid #EF9F27; border-radius: 8px;"
            "padding: 12px 14px; font-size: 12px;"
        )
