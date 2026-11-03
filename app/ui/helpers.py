"""界面小工具：表格填充、数字格式化、胶囊标签。

页面里的表格列很多，统一在这里处理对齐、斑马纹和状态配色，
避免每个页面复制一遍。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
)

from app.ui.theme import COLORS


def setup_table(
    table: QTableWidget,
    headers: list[str],
    column_widths: dict[int, int] | None = None,
    stretch_last: bool = True,
) -> None:
    """统一表格外观：整行选择、只读、斑马纹、表头。"""
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(30)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    if stretch_last:
        table.horizontalHeader().setStretchLastSection(True)
    table.setSortingEnabled(False)
    if column_widths:
        for index, width in column_widths.items():
            table.setColumnWidth(index, width)


def fill_table(
    table: QTableWidget,
    rows: list[list],
    numeric_columns: set[int] | None = None,
    row_colors: dict[int, tuple[str, str]] | None = None,
    bold_columns: set[int] | None = None,
) -> None:
    """填充表格。

    参数
        rows:           二维数据，None 显示为 "—"
        numeric_columns: 这些列右对齐
        row_colors:     {行号: (背景色, 前景色)}
        bold_columns:   这些列加粗
    """
    numeric_columns = numeric_columns or set()
    bold_columns = bold_columns or set()
    row_colors = row_colors or {}

    table.setUpdatesEnabled(False)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            text = "—" if value is None else str(value)
            item = QTableWidgetItem(text)
            if c in numeric_columns:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            if c in bold_columns:
                font = QFont()
                font.setBold(True)
                item.setFont(font)
            if r in row_colors:
                background, foreground = row_colors[r]
                item.setBackground(QColor(background))
                item.setForeground(QColor(foreground))
            table.setItem(r, c, item)
    table.setUpdatesEnabled(True)


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def hint_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def page_hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("PageHint")
    label.setWordWrap(True)
    return label


_PILL_STYLES = {
    "green": (COLORS["green_soft"], COLORS["green_dark"]),
    "amber": (COLORS["amber_soft"], "#6B3F0A"),
    "red": (COLORS["red_soft"], "#8C2222"),
    "blue": (COLORS["blue_soft"], COLORS["blue"]),
}


def pill(text: str, kind: str = "green") -> QLabel:
    """状态胶囊：green / amber / red / blue。"""
    label = QLabel(text)
    label.setAlignment(Qt.AlignCenter)
    style_pill(label, text, kind)
    return label


def style_pill(label: QLabel, text: str, kind: str = "green") -> None:
    """动态改胶囊文字与颜色（改 objectName 不会自动重绘，直接写内联样式）。"""
    background, foreground = _PILL_STYLES.get(kind, _PILL_STYLES["green"])
    label.setText(text)
    label.setStyleSheet(
        f"background: {background}; color: {foreground}; border-radius: 10px;"
        " padding: 3px 10px; font-size: 12px;"
    )
    label.ensurePolished()
    label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    # QLabel 不会因为 QSS 字号自动重算 layout 宽度，显式按字体宽度留足空间
    label.setMinimumWidth(label.fontMetrics().horizontalAdvance(text) + 28)


def fmt_num(value, digits: int = 2, dash: bool = True) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—" if dash else "0"
    if number != number:  # NaN
        return "—" if dash else "0"
    return f"{number:,.{digits}f}"


def fmt_int(value) -> str:
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(value, digits: int = 1) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def verdict_color(verdict: str) -> tuple[str, str] | None:
    return {
        "畅销": (COLORS["green_soft"], COLORS["green_dark"]),
        "正常": None,
        "滞销": (COLORS["amber_soft"], "#6B3F0A"),
        "呆滞": (COLORS["red_soft"], COLORS["red"]),
    }.get(verdict)
