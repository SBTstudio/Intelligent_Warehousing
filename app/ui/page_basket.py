"""购物篮分析页。

对应需求：2.1 输入量 1
工作项：M3 Apriori 关联规则挖掘

界面展示支持度、置信度、提升度（保留 3 位小数），并额外画出 lift 热力图。
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.core import basket
from app.db import schema
from app.ui.base_page import WorkPage
from app.ui.helpers import fill_table, hint_label, pill, setup_table, style_pill
from app.ui.worker import FunctionWorker


class BasketPage(WorkPage):
    def __init__(self):
        super().__init__(
            "购物篮分析",
            "挖掘同时被购买的商品组合，输出支持度、置信度与提升度（lift）。"
            "lift > 1 表示存在正向连带购买关系，可用于优化货架陈列。",
        )
        self.setWindowTitle("购物篮分析")
        self._worker: FunctionWorker | None = None
        self._chart = None

        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addWidget(QLabel("最小支持度"))
        self.sp_support = QDoubleSpinBox()
        self.sp_support.setRange(0.001, 0.500)
        self.sp_support.setSingleStep(0.005)
        self.sp_support.setDecimals(3)
        self.sp_support.setValue(0.010)
        self.sp_support.setFixedWidth(100)
        self.sp_support.setToolTip("低于该支持度的商品组合会被当作噪声剪掉")
        controls.addWidget(self.sp_support)

        self.cb_positive = QCheckBox("只看正向连带（lift > 1）")
        self.cb_positive.setChecked(True)
        controls.addWidget(self.cb_positive)
        controls.addSpacing(6)

        self.btn_run = QPushButton("开始分析")
        controls.addWidget(self.btn_run)
        controls.addStretch(1)
        self.status = pill("等待分析", "amber")
        self.status.setVisible(False)
        controls.addWidget(self.status)
        self.body.addLayout(controls)

        self.lbl_meta = hint_label(
            "建议先到「数据导入」页载入示例数据；规则按 lift 从高到低排列。"
        )
        self.lbl_meta.setWordWrap(True)
        self.body.addWidget(self.lbl_meta)

        self.splitter = QSplitter(Qt.Vertical)
        self.table = QTableWidget()
        setup_table(
            self.table,
            ["SKU A", "商品 A", "SKU B", "商品 B", "支持度", "置信度", "提升度", "关联强度"],
            {0: 82, 1: 150, 2: 82, 3: 150, 4: 86, 5: 86, 6: 86},
        )
        self.splitter.addWidget(self.table)

        self.chart_holder = QWidget()
        self.chart_layout = QVBoxLayout(self.chart_holder)
        self.chart_layout.setContentsMargins(0, 0, 0, 0)
        self.chart_holder.setVisible(False)
        self.splitter.addWidget(self.chart_holder)
        self.splitter.setSizes([430, 250])
        self.body.addWidget(self.splitter, 1)

        self.btn_run.clicked.connect(self._run)
        self._load_config()

    # ==========================================================
    def _load_config(self) -> None:
        try:
            config = schema.get_config()
            self.sp_support.setValue(float(config.get("min_support", "0.010")))
        except Exception:
            pass

    def _run(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        records = schema.fetch_sales()
        if not records:
            style_pill(self.status, "数据库为空，请先导入数据", "amber")
            self.status.setVisible(True)
            self.lbl_meta.setText(
                "没有读到销售明细。请到「数据导入」页点击「一键载入示例数据」。"
            )
            return

        min_support = self.sp_support.value()
        only_positive = self.cb_positive.isChecked()
        self.btn_run.setEnabled(False)
        self.btn_run.setText("分析中…")
        style_pill(self.status, "正在挖掘频繁项集…", "blue")
        self.status.setVisible(True)

        def job():
            started = time.perf_counter()
            baskets = basket.build_baskets(records)
            rules = basket.mine_rules(
                baskets,
                min_support=min_support,
                min_confidence=0.3,
                only_positive=only_positive,
            )
            elapsed = time.perf_counter() - started
            products = {
                row["sku_id"]: (row.get("sku_name") or row["sku_id"])
                for row in schema.fetch_products()
            }
            return rules, len(baskets), elapsed, products

        self._worker = FunctionWorker(job)
        self._worker.succeeded.connect(self._render)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def shutdown(self) -> None:
        from app.ui.worker import stop_worker

        stop_worker(self._worker)


    # ==========================================================
    def _render(self, payload) -> None:
        rules, basket_count, elapsed, products = payload
        self.btn_run.setEnabled(True)
        self.btn_run.setText("开始分析")

        rows = []
        positive = 0
        row_colors = {}
        for index, rule in enumerate(rules[:300]):
            if rule.lift > 1:
                positive += 1
            strength = "强连带" if rule.lift >= 3 else ("正向" if rule.lift > 1 else "弱/负向")
            rows.append(
                [
                    rule.antecedent,
                    products.get(rule.antecedent, rule.antecedent),
                    rule.consequent,
                    products.get(rule.consequent, rule.consequent),
                    f"{rule.support:.3f}",
                    f"{rule.confidence:.3f}",
                    f"{rule.lift:.3f}",
                    strength,
                ]
            )
            if rule.lift >= 3:
                row_colors[index] = ("#E1F5EE", "#0B5542")

        fill_table(
            self.table,
            rows,
            numeric_columns={4, 5, 6},
            row_colors=row_colors,
            bold_columns={6},
        )

        if rules:
            style_pill(
                self.status,
                f"完成 · {len(rules)} 条规则 · 正向 {positive} 条",
                "green",
            )
            self.lbl_meta.setText(
                f"购物篮 {basket_count} 张　最小支持度 {self.sp_support.value():.3f}"
                f"　最小置信度 0.300　耗时 {elapsed:.2f} 秒"
                + ("　仅显示前 300 条" if len(rules) > 300 else "")
            )
            self._draw_chart(rules, products)
        else:
            style_pill(self.status, "没有挖掘出规则", "amber")
            self.lbl_meta.setText(
                "当前支持度 / 置信度下没有关联规则。可以尝试降低最小支持度，"
                "或导入更多小票数据。"
            )
            if self._chart is not None:
                self._chart.draw_empty("暂无符合条件的关联规则")
                self.chart_holder.setVisible(True)
        self.status.setVisible(True)

    def _draw_chart(self, rules, products) -> None:
        if self._chart is None:
            from app.ui.widgets.chart_view import ChartCanvas

            self._chart = ChartCanvas(self, width=9.0, height=2.8)
            self.chart_layout.addWidget(self._chart)
        labels, matrix = basket.lif_matrix(rules, top_n=10)
        display = [products.get(label, label) for label in labels]
        display = [name[:7] + "…" if len(name) > 8 else name for name in display]
        self._chart.draw_heatmap(matrix, display)
        self.chart_holder.setMinimumHeight(220)
        self.chart_holder.setVisible(True)
        self.splitter.setSizes([420, 250])

    def _failed(self, message: str) -> None:
        self.btn_run.setEnabled(True)
        self.btn_run.setText("开始分析")
        style_pill(self.status, "分析失败", "red")
        self.status.setVisible(True)
        self.lbl_meta.setText(message)

    def on_data_changed(self, source: str = "") -> None:
        style_pill(self.status, "数据已更新，点击开始分析", "amber")
        self.status.setVisible(True)
        self.lbl_meta.setText("检测到新的导入数据，重新分析即可看到最新规则。")
