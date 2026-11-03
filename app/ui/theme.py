"""界面主题：配色、字体与全局 QSS。

把视觉样式集中在一个文件里，页面只关心布局和数据，不写零散的颜色值。
配色参考低饱和的"纸张 + 墨绿"风格，长时间看表格不刺眼。
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

COLORS = {
    "bg": "#F5F4EE",
    "card": "#FFFFFF",
    "ink": "#24231F",
    "muted": "#6B6A64",
    "border": "#E2DFD4",
    "green": "#0F6E56",
    "green_dark": "#0B5542",
    "green_soft": "#E1F5EE",
    "amber": "#B7791F",
    "amber_soft": "#FAEEDA",
    "red": "#A32D2D",
    "red_soft": "#FCEBEB",
    "blue": "#2F5EA8",
    "blue_soft": "#E8F0FB",
}

QSS = """
QWidget {
    color: #24231F;
    font-size: 13px;
}

QMainWindow, QDialog {
    background: #F5F4EE;
}

QStatusBar {
    background: #FFFFFF;
    border-top: 1px solid #E2DFD4;
    color: #6B6A64;
    font-size: 12px;
}
QStatusBar::item { border: none; }

QPushButton {
    background: #0F6E56;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton:hover { background: #0B5542; }
QPushButton:pressed { background: #093F31; }
QPushButton:disabled { background: #D5D2C7; color: #FBFAF6; }

QPushButton[variant="ghost"] {
    background: #FFFFFF;
    color: #0F6E56;
    border: 1px solid #BFDCCF;
    font-weight: 500;
}
QPushButton[variant="ghost"]:hover { background: #E1F5EE; }
QPushButton[variant="ghost"]:disabled { color: #B7B4A9; border-color: #E2DFD4; background: #F7F6F1; }

QPushButton[variant="danger"] {
    background: #FFFFFF;
    color: #A32D2D;
    border: 1px solid #E9C5C5;
    font-weight: 500;
}
QPushButton[variant="danger"]:hover { background: #FCEBEB; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #FFFFFF;
    border: 1px solid #D8D5C9;
    border-radius: 7px;
    padding: 5px 9px;
    min-height: 22px;
    selection-background-color: #BFE5D8;
    selection-color: #0B4F3E;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #0F6E56;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 16px;
    border: none;
    background: transparent;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E2DFD4;
    selection-background-color: #E1F5EE;
    selection-color: #0B5542;
    outline: none;
}

QTableWidget {
    background: #FFFFFF;
    border: 1px solid #E2DFD4;
    border-radius: 8px;
    gridline-color: #F0EEE6;
    alternate-background-color: #FBFAF6;
    selection-background-color: #E1F5EE;
    selection-color: #0B4F3E;
    outline: none;
}
QTableWidget::item { padding: 5px 7px; }
QHeaderView::section {
    background: #F1EFE6;
    color: #4D4C46;
    border: none;
    border-bottom: 1px solid #E2DFD4;
    border-right: 1px solid #E9E6DC;
    padding: 8px 7px;
    font-size: 12px;
    font-weight: 600;
}
QTableCornerButton::section { background: #F1EFE6; border: none; }

QTabWidget::pane {
    border: 1px solid #E2DFD4;
    border-radius: 8px;
    background: #FFFFFF;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #6B6A64;
    padding: 8px 18px;
    margin-right: 4px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:hover { color: #0F6E56; }
QTabBar::tab:selected {
    color: #0F6E56;
    border-bottom: 2px solid #0F6E56;
    font-weight: 600;
}

QTextEdit {
    background: #FFFFFF;
    border: 1px solid #E2DFD4;
    border-radius: 8px;
    padding: 12px;
    font-size: 13px;
    selection-background-color: #BFE5D8;
}

QLabel#PageTitle {
    font-size: 22px;
    font-weight: 600;
    color: #24231F;
}
QLabel#PageHint {
    font-size: 13px;
    color: #6B6A64;
}
QLabel#SectionTitle {
    font-size: 13px;
    font-weight: 600;
    color: #24231F;
}
QLabel#Muted {
    color: #6B6A64;
    font-size: 12px;
}
QLabel#PillGreen {
    background: #E1F5EE;
    color: #0B5542;
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 12px;
}
QLabel#PillAmber {
    background: #FAEEDA;
    color: #7A4B0F;
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 12px;
}
QLabel#PillRed {
    background: #FCEBEB;
    color: #8C2222;
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 12px;
}
QLabel#Banner {
    background: #FAEEDA;
    color: #6B3F0A;
    border: 1px solid #E9C58B;
    border-radius: 8px;
    padding: 9px 12px;
    font-size: 12px;
}

QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item {
    height: 42px;
    padding-left: 16px;
    border-radius: 8px;
    margin: 2px 10px;
    color: #4D4C46;
}
QListWidget::item:hover { background: #EDEBE1; }
QListWidget::item:selected {
    background: #FFFFFF;
    color: #0F6E56;
    font-weight: 600;
    border-left: 3px solid #0F6E56;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #CFCCC0;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: #B7B4A7; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #CFCCC0;
    border-radius: 5px;
    min-width: 28px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QToolTip {
    background: #24231F;
    color: #FFFFFF;
    border: none;
    padding: 6px 8px;
    border-radius: 6px;
}
"""


def apply_theme(app: QApplication) -> None:
    """设置全局字体、Fusion 风格与 QSS。"""
    app.setStyle("Fusion")

    font = QFont()
    # Qt 会用第一个能成功匹配的字体族；中英文混排时英文走系统默认
    font.setFamilies(
        [
            "PingFang SC",
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "Segoe UI",
        ]
    )
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(QSS)
