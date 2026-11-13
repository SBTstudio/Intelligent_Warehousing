"""主窗口：左侧导航 + 右侧页面切换 + 底部状态栏。"""

from __future__ import annotations

import contextlib

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.db import schema
from app.llm import tasks
from app.llm.client import get_client
from app.paths import resource_path
from app.ui.page_basket import BasketPage
from app.ui.page_import import ImportPage
from app.ui.page_realtime import RealtimePage
from app.ui.page_replenish import ReplenishPage
from app.ui.page_report import ReportPage
from app.ui.page_settings import SettingsPage
from app.ui.theme import COLORS
from app.ui.worker import FunctionWorker, stop_worker

VERSION = "1.0.3"
NAV_LABELS = [
    "数据导入",
    "实时库存",
    "购物篮分析",
    "库存与补货",
    "分析报告",
    "参数配置",
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("智能仓储管理系统 · Smart WMS")
        self.resize(1320, 840)
        self.setMinimumSize(1120, 740)

        icon_path = resource_path("assets", "app_icon.svg")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        central = QWidget()
        central.setObjectName("Root")
        central.setStyleSheet("QWidget#Root { background: #F5F4EE; }")
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.pages = [
            ImportPage(),
            RealtimePage(),
            BasketPage(),
            ReplenishPage(),
            ReportPage(),
            SettingsPage(),
        ]
        for page in self.pages:
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        self._build_statusbar()

        self.nav.currentRowChanged.connect(self._change_page)
        self.nav.setCurrentRow(0)

        self.import_page = self.pages[0]
        self.realtime_page = self.pages[1]
        self.basket_page = self.pages[2]
        self.replenish_page = self.pages[3]
        self.report_page = self.pages[4]
        self.settings_page = self.pages[5]

        self.import_page.data_imported.connect(self._on_data_imported)
        self.realtime_page.data_changed.connect(self._on_data_imported)
        self.settings_page.config_changed.connect(self._on_config_changed)

        self._model_worker: FunctionWorker | None = None
        QTimer.singleShot(150, self._refresh_db_label)
        QTimer.singleShot(600, self._check_model)

    # ==========================================================
    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(212)
        sidebar.setStyleSheet(
            "QWidget#Sidebar { background: #EDEBE1; border: none; }"
        )
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 22, 0, 18)
        layout.setSpacing(0)

        brand = QLabel("智能仓储")
        brand.setObjectName("Brand")
        brand.setStyleSheet(
            f"color: {COLORS['green']}; font-size: 20px; font-weight: 700;"
            "padding-left: 22px; letter-spacing: 2px;"
        )
        layout.addWidget(brand)

        subtitle = QLabel("SMART WMS  ·  v1.0.3")
        subtitle.setStyleSheet(
            f"color: {COLORS['muted']}; font-size: 10px; padding-left: 23px;"
            "letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(subtitle)
        layout.addSpacing(20)

        self.nav = QListWidget()
        self.nav.setFocusPolicy(Qt.NoFocus)
        for index, label in enumerate(NAV_LABELS, start=1):
            item = QListWidgetItem(f"{index:02d}   {label}")
            self.nav.addItem(item)
        self.nav.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { height: 42px; padding-left: 14px; border-radius: 8px;"
            " margin: 2px 10px; color: #4D4C46; font-size: 13px; }"
            "QListWidget::item:hover { background: #E3E0D5; }"
            "QListWidget::item:selected { background: #FFFFFF; color: #0F6E56;"
            " font-weight: 600; border-left: 3px solid #0F6E56; }"
        )
        layout.addWidget(self.nav, 1)

        foot = QLabel("Python 3.12 · SQLite · Ollama / API\n数据默认保存在本机")
        foot.setStyleSheet(
            "color: #8A887F; font-size: 10px; padding-left: 22px;"
            "line-height: 1.6; background: transparent;"
        )
        layout.addWidget(foot)
        return sidebar

    def _build_statusbar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("padding-left: 8px; color: #6B6A64;")
        bar.addWidget(self.status_label, 1)

        self.db_label = QLabel("数据库：未初始化")
        self.db_label.setStyleSheet("color: #6B6A64; padding-right: 14px;")
        bar.addPermanentWidget(self.db_label)

        self.model_label = QLabel("模型：检测中…")
        self.model_label.setStyleSheet("color: #6B6A64; padding-right: 10px;")
        bar.addPermanentWidget(self.model_label)

    # ==========================================================
    def _change_page(self, index: int) -> None:
        if not 0 <= index < len(self.pages):
            return
        self.stack.setCurrentIndex(index)
        page = self.pages[index]
        on_show = getattr(page, "on_show", None)
        if callable(on_show):
            on_show()
        self._refresh_db_label()

    def _on_data_imported(self, kind: str) -> None:
        for page in self.pages:
            handler = getattr(page, "on_data_changed", None)
            if callable(handler) and page is not self.import_page:
                with contextlib.suppress(Exception):
                    handler(kind)
        self._refresh_db_label()
        self.status_label.setText("数据已更新，可以到分析页面查看结果")

    def _on_config_changed(self) -> None:
        self.replenish_page.on_config_changed()
        self.report_page.on_config_changed()
        self.status_label.setText("参数已保存，补货与分类结果将在下次计算时生效")

    def _refresh_db_label(self) -> None:
        try:
            stats = schema.db_stats()
            self.db_label.setText(
                f"数据库 {stats['size_mb']} MB · 明细 {stats['transaction_items']:,} 行"
                f" · 库存流水 {stats.get('inventory_events', 0):,} 条"
            )
            self.db_label.setToolTip(
                f"{schema.DB_PATH}\n跨度 {stats['span_days']} 天，"
                f"商品 {stats['products']} 个"
            )
        except Exception:
            self.db_label.setText("数据库：读取失败")

    def _check_model(self) -> None:
        if self._model_worker is not None and self._model_worker.isRunning():
            return

        def job():
            return tasks.health_check()

        self._model_worker = FunctionWorker(job)
        self._model_worker.succeeded.connect(self._apply_model_status)
        self._model_worker.failed.connect(
            lambda message: self.model_label.setText(f"模型：检测失败（{message}）")
        )
        self._model_worker.start()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        for page in self.pages:
            shutdown = getattr(page, "shutdown", None)
            if callable(shutdown):
                shutdown()
        stop_worker(self._model_worker)
        super().closeEvent(event)

    def _apply_model_status(self, result) -> None:
        available, message = result
        client = get_client()
        prefix = "第三方 API" if client.is_remote else "本地模型"
        if available:
            self.model_label.setText(f"{prefix}：在线")
            self.model_label.setStyleSheet(
                f"color: {COLORS['green']}; padding-right: 10px; font-weight: 600;"
            )
            self.model_label.setToolTip(message)
        else:
            self.model_label.setText(f"{prefix}：不可用 · 统计模式")
            self.model_label.setStyleSheet(
                f"color: {COLORS['amber']}; padding-right: 10px; font-weight: 600;"
            )
            self.model_label.setToolTip(message)
