"""补货建议页。

对应需求：1.1 目标 1、2.1 输入量 2
工作项：M4 补货预测、M5 畅销滞销判定、M6 可视化

三个页签：
    补货建议   —— 安全库存 / 补货点 / 剩余天数 / 建议补货日
    畅销 / 滞销 —— ABC × XYZ 交叉分类结果
    图表       —— 销售额柱状图 + 单 SKU 销量折线图
"""

from __future__ import annotations

import time

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core import classify, replenish
from app.db import schema
from app.ui.base_page import WorkPage
from app.ui.helpers import (
    fill_table,
    fmt_num,
    hint_label,
    pill,
    setup_table,
    style_pill,
    verdict_color,
)
from app.ui.theme import COLORS
from app.ui.worker import FunctionWorker

VERDICT_BAR_COLORS = {
    "畅销": COLORS["green"],
    "正常": COLORS["blue"],
    "滞销": COLORS["amber"],
    "呆滞": COLORS["red"],
}


class ReplenishPage(WorkPage):
    def __init__(self):
        super().__init__(
            "库存与补货",
            "结合现有库存与日均消耗速度，计算安全库存、补货点与建议补货日期；"
            "同时用 ABC × XYZ 交叉分类给出畅销 / 滞销商品清单。",
        )
        self.setWindowTitle("库存与补货")
        self._worker: FunctionWorker | None = None
        self._series_map: dict[str, list[tuple]] = {}
        self._suggestions: list = []
        self._profiles: list = []
        self._line_chart = None
        self._bar_chart = None

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.btn_run = QPushButton("计算补货与分类")
        controls.addWidget(self.btn_run)
        self.status = pill("等待计算", "amber")
        self.status.setVisible(False)
        controls.addWidget(self.status)
        controls.addStretch(1)
        self.body.addLayout(controls)

        self.lbl_meta = hint_label("参数取自「参数配置」页：提前期、服务水平、滞销阈值。")
        self.body.addWidget(self.lbl_meta)

        self.tabs = QTabWidget()
        self.tbl_replenish = QTableWidget()
        setup_table(
            self.tbl_replenish,
            [
                "SKU", "商品名", "现有库存", "日均销量", "需求波动",
                "安全库存", "补货点", "剩余天数", "建议补货日", "建议补货量", "状态",
            ],
            {0: 78, 1: 150, 2: 84, 3: 84, 4: 84, 5: 84, 6: 84, 7: 78, 8: 108, 9: 92},
        )
        self.tabs.addTab(self.tbl_replenish, "补货建议")

        self.tbl_slowfast = QTableWidget()
        setup_table(
            self.tbl_slowfast,
            ["SKU", "商品名", "销售额", "销售额占比", "ABC", "CV", "XYZ", "周转天数", "判定"],
            {0: 78, 1: 160, 2: 100, 3: 92, 4: 58, 5: 70, 6: 58, 7: 88},
        )
        self.tabs.addTab(self.tbl_slowfast, "畅销 / 滞销")

        self.tab_chart = QWidget()
        chart_layout = QVBoxLayout(self.tab_chart)
        chart_layout.setContentsMargins(12, 10, 12, 10)
        chart_layout.setSpacing(8)

        chart_top = QHBoxLayout()
        chart_top.addWidget(QLabel("SKU 销量走势"))
        self.cb_sku = QComboBox()
        self.cb_sku.setMinimumWidth(220)
        self.cb_sku.currentIndexChanged.connect(self._draw_line)
        chart_top.addWidget(self.cb_sku)
        chart_top.addStretch(1)
        chart_layout.addLayout(chart_top)

        charts = QHBoxLayout()
        self.line_holder = QWidget()
        self.line_layout = QVBoxLayout(self.line_holder)
        self.line_layout.setContentsMargins(0, 0, 0, 0)
        self.bar_holder = QWidget()
        self.bar_layout = QVBoxLayout(self.bar_holder)
        self.bar_layout.setContentsMargins(0, 0, 0, 0)
        charts.addWidget(self.line_holder, 1)
        charts.addWidget(self.bar_holder, 1)
        chart_layout.addLayout(charts, 1)
        self.tabs.addTab(self.tab_chart, "图表")

        self.body.addWidget(self.tabs, 1)

        self.btn_run.clicked.connect(self._run)

    # ==========================================================
    def _run(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        records = schema.fetch_sales()
        inventory = schema.fetch_inventory()
        if not records:
            style_pill(self.status, "数据库为空，请先导入销售数据", "amber")
            self.status.setVisible(True)
            self.lbl_meta.setText("没有销售记录，无法计算日均销量。请先在「数据导入」页载入示例数据。")
            return

        config = schema.get_config()
        lead_time = int(float(config.get("lead_time_days", "3")))
        service_level = float(config.get("service_level", "0.95"))
        replenish_days = int(float(config.get("replenish_days", "7")))
        slow_days = int(float(config.get("slow_turnover_days", "45")))

        self.btn_run.setEnabled(False)
        self.btn_run.setText("计算中…")
        style_pill(self.status, "正在计算安全库存与分类…", "blue")
        self.status.setVisible(True)

        def job():
            started = time.perf_counter()
            suggestions = replenish.build_all_suggestions(
                records,
                inventory,
                lead_time_days=lead_time,
                service_level=service_level,
                replenish_days=replenish_days,
            )
            profiles = classify.analyze(records, inventory, slow_turnover_days=slow_days)
            series_map = {
                profile.sku_id: replenish.daily_series(records, profile.sku_id)
                for profile in profiles[:12]
            }
            elapsed = time.perf_counter() - started
            return suggestions, profiles, series_map, elapsed

        self._worker = FunctionWorker(job)
        self._worker.succeeded.connect(self._render)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def shutdown(self) -> None:
        from app.ui.worker import stop_worker

        stop_worker(self._worker)


    # ==========================================================
    def _render(self, payload) -> None:
        suggestions, profiles, series_map, elapsed = payload
        self._suggestions = suggestions
        self._profiles = profiles
        self._series_map = series_map
        self.btn_run.setEnabled(True)
        self.btn_run.setText("计算补货与分类")

        self._fill_replenish(suggestions)
        self._fill_slowfast(profiles)

        urgent = sum(1 for item in suggestions if item.urgent)
        slow = sum(1 for item in profiles if item.verdict in ("滞销", "呆滞"))
        style_pill(
            self.status,
            f"完成 · {len(suggestions)} 个 SKU · {urgent} 个需补货 · {slow} 个滞销",
            "green" if urgent else "blue",
        )
        self.status.setVisible(True)
        self.lbl_meta.setText(
            f"提前期 {self._lead_time()} 天　服务水平 {self._service_level():.2%}"
            f"　耗时 {elapsed:.2f} 秒"
        )

        self._fill_sku_combo(profiles)
        self._draw_bar(profiles)
        self._draw_line()

    def _fill_replenish(self, suggestions) -> None:
        rows = []
        colors = {}
        for index, item in enumerate(suggestions):
            urgent = item.urgent
            rows.append(
                [
                    item.sku_id,
                    item.sku_name or "—",
                    fmt_num(item.stock_qty, 0),
                    fmt_num(item.daily_sales, 2),
                    fmt_num(item.demand_std, 2),
                    fmt_num(item.safety_stock, 1),
                    fmt_num(item.reorder_point, 1),
                    "—" if item.daily_sales <= 0 else fmt_num(item.days_left, 1),
                    item.suggest_date.strftime("%Y-%m-%d") if item.suggest_date else "—",
                    fmt_num(item.suggest_qty, 0),
                    "需补货" if urgent else "正常",
                ]
            )
            if urgent:
                colors[index] = (COLORS["red_soft"], COLORS["red"])
        fill_table(
            self.tbl_replenish,
            rows,
            numeric_columns={2, 3, 4, 5, 6, 7, 9},
            row_colors=colors,
            bold_columns={10},
        )
        self.tabs.setTabText(0, f"补货建议（{len(suggestions)}）")

    def _fill_slowfast(self, profiles) -> None:
        rows = []
        colors = {}
        for index, item in enumerate(profiles):
            rows.append(
                [
                    item.sku_id,
                    item.sku_name or "—",
                    fmt_num(item.sales_amount, 2),
                    f"{item.sales_amount_ratio * 100:.1f}%",
                    item.abc_class,
                    fmt_num(item.cv, 3),
                    item.xyz_class,
                    "—" if item.turnover_days >= 9999 else fmt_num(item.turnover_days, 1),
                    item.verdict,
                ]
            )
            color = verdict_color(item.verdict)
            if color:
                colors[index] = color
        fill_table(
            self.tbl_slowfast,
            rows,
            numeric_columns={2, 3, 5, 7},
            row_colors=colors,
            bold_columns={8},
        )
        self.tabs.setTabText(1, f"畅销 / 滞销（{len(profiles)}）")

    def _fill_sku_combo(self, profiles) -> None:
        self.cb_sku.blockSignals(True)
        self.cb_sku.clear()
        for profile in profiles[:12]:
            label = f"{profile.sku_id} · {profile.sku_name or '未命名'}"
            self.cb_sku.addItem(label, profile.sku_id)
        self.cb_sku.blockSignals(False)
        if self.cb_sku.count():
            self.cb_sku.setCurrentIndex(0)

    # ==========================================================
    def _ensure_charts(self) -> None:
        if self._line_chart is None:
            from app.ui.widgets.chart_view import ChartCanvas

            self._line_chart = ChartCanvas(self, width=5.0, height=2.9)
            self.line_layout.addWidget(self._line_chart)
        if self._bar_chart is None:
            from app.ui.widgets.chart_view import ChartCanvas

            self._bar_chart = ChartCanvas(self, width=5.0, height=2.9)
            self.bar_layout.addWidget(self._bar_chart)

    def _draw_line(self, *args) -> None:
        if not self._series_map:
            return
        sku = self.cb_sku.currentData()
        if not sku:
            return
        series = self._series_map.get(sku) or []
        if not series:
            self._ensure_charts()
            self._line_chart.draw_empty("该 SKU 暂无销售序列")
            return
        self._ensure_charts()
        x = [day for day, _ in series]
        y = [qty for _, qty in series]
        name = self.cb_sku.currentText()
        self._line_chart.draw_line(x, y, title=f"{name} 日销量", xlabel="日期", ylabel="销量")

    def _draw_bar(self, profiles) -> None:
        self._ensure_charts()
        top = profiles[:10]
        labels = [item.sku_name or item.sku_id for item in top]
        labels = [name[:6] + "…" if len(name) > 7 else name for name in labels]
        values = [item.sales_amount for item in top]
        colors = [VERDICT_BAR_COLORS.get(item.verdict, COLORS["blue"]) for item in top]
        self._bar_chart.draw_bar_colors(labels, values, colors, title="销售额 TOP10")

    # ==========================================================
    def _lead_time(self) -> int:
        try:
            return int(float(schema.get_config().get("lead_time_days", "3")))
        except Exception:
            return 3

    def _service_level(self) -> float:
        try:
            return float(schema.get_config().get("service_level", "0.95"))
        except Exception:
            return 0.95

    def _failed(self, message: str) -> None:
        self.btn_run.setEnabled(True)
        self.btn_run.setText("计算补货与分类")
        style_pill(self.status, "计算失败", "red")
        self.status.setVisible(True)
        self.lbl_meta.setText(message)

    def on_data_changed(self, source: str = "") -> None:
        style_pill(self.status, "数据已更新，点击重新计算", "amber")
        self.status.setVisible(True)

    def on_config_changed(self) -> None:
        style_pill(self.status, "参数已更新，点击重新计算", "amber")
        self.status.setVisible(True)
