"""分析报告页。

对应需求：2.2.2 输出与展示一般性规定、2.2.3 模型调用一般性规定
工作项：M8 文字报告生成、M10 历史报告回看、M13 热点映射

五类报告：
    经营周报 / 滞销归因 / 陈列建议 / 换季推荐 / 热点映射

所有数字由算法层算好，本地模型只做文字解读；模型不可用时自动切换为
「基础统计模式」，页面顶部会显示提示条，不会白屏或崩溃。
"""

from __future__ import annotations

import json
from datetime import date, datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
)

from app.core import basket, classify, replenish
from app.db import schema
from app.llm import prompts, tasks
from app.llm.client import get_client
from app.ui.base_page import WorkPage
from app.ui.helpers import hint_label, pill, style_pill
from app.ui.worker import FunctionWorker

REPORT_TYPES = [
    ("weekly", "经营周报"),
    ("slow", "滞销归因"),
    ("layout", "陈列建议"),
    ("seasonal", "换季推荐"),
    ("trend", "热点映射"),
]
REPORT_LABELS = dict(REPORT_TYPES)


class ReportPage(WorkPage):
    def __init__(self):
        super().__init__(
            "分析报告",
            "由本地大模型或第三方 OpenAI 兼容 API 把算法结果解读为经营建议。"
            "所有数值均来自算法层，模型只负责文字表达，不参与计算；"
            "模型不可用时自动降级为基础统计模式。",
        )
        self.setWindowTitle("分析报告")
        self._worker: FunctionWorker | None = None
        self._status_worker: FunctionWorker | None = None
        self._last_report: tuple[str, str, int] | None = None
        self._history: dict[str, tuple[str, int]] = {}

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(QLabel("报告类型"))
        self.cb_type = QComboBox()
        for key, label in REPORT_TYPES:
            self.cb_type.addItem(label, key)
        self.cb_type.setMinimumWidth(140)
        self.cb_type.currentIndexChanged.connect(self._on_type_changed)
        top.addWidget(self.cb_type)

        self.btn_gen = QPushButton("生成报告")
        top.addWidget(self.btn_gen)
        self.btn_copy = QPushButton("复制全文")
        self.btn_copy.setProperty("variant", "ghost")
        top.addWidget(self.btn_copy)
        self.btn_save = QPushButton("保存到历史")
        self.btn_save.setProperty("variant", "ghost")
        self.btn_save.setEnabled(False)
        top.addWidget(self.btn_save)
        top.addStretch(1)
        self.status = pill("等待生成", "amber")
        self.status.setVisible(False)
        top.addWidget(self.status)
        self.body.addLayout(top)

        self.banner = QLabel("")
        self.banner.setObjectName("Banner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        self.body.addWidget(self.banner)

        self.lbl_meta = hint_label("模型状态检测中…")
        self.body.addWidget(self.lbl_meta)

        self.hot_input = QTextEdit()
        self.hot_input.setPlaceholderText(
            "粘贴一段网络热点内容（例如平台热搜、行业资讯摘要），"
            "系统会把它映射到店内现有品类。留空则只使用当前销售数据。"
        )
        self.hot_input.setMaximumHeight(76)
        self.hot_input.setVisible(False)
        self.body.addWidget(self.hot_input)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(300)
        self.body.addWidget(self.text, 1)

        history_row = QHBoxLayout()
        history_row.addWidget(QLabel("历史报告"))
        self.cb_history = QComboBox()
        self.cb_history.setMinimumWidth(280)
        history_row.addWidget(self.cb_history)
        self.btn_load = QPushButton("载入")
        self.btn_load.setProperty("variant", "ghost")
        history_row.addWidget(self.btn_load)
        history_row.addStretch(1)
        self.body.addLayout(history_row)

        self.btn_gen.clicked.connect(self._run)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_save.clicked.connect(self._save)
        self.btn_load.clicked.connect(self._load_history)
        self.cb_history.currentIndexChanged.connect(self._load_history)

        self._refresh_history()
        QTimer.singleShot(900, self._check_status)

    # ==========================================================
    def _on_type_changed(self, *args) -> None:
        self.hot_input.setVisible(self.cb_type.currentData() == "trend")

    def _check_status(self) -> None:
        def job():
            return tasks.health_check()

        self._status_worker = FunctionWorker(job)
        self._status_worker.succeeded.connect(self._apply_status)
        self._status_worker.failed.connect(
            lambda message: self.lbl_meta.setText(f"模型状态检测失败：{message}")
        )
        self._status_worker.start()

    def _apply_status(self, result) -> None:
        available, message = result
        client = get_client()
        prefix = "第三方 API" if client.is_remote else "本地模型"
        if available:
            self.lbl_meta.setText(message)
            style_pill(self.status, f"{prefix}在线", "green")
        else:
            self.lbl_meta.setText(message + "　（报告仍可生成，使用模板兜底）")
            style_pill(self.status, "基础统计模式", "amber")
        self.status.setVisible(True)

    # ==========================================================
    def _run(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        report_type = self.cb_type.currentData()
        trend_text = self.hot_input.toPlainText().strip()
        if report_type == "trend" and not trend_text:
            style_pill(self.status, "请先粘贴热点文本", "amber")
            self.status.setVisible(True)
            return

        records = schema.fetch_sales()
        if not records:
            style_pill(self.status, "数据库为空，请先导入数据", "amber")
            self.status.setVisible(True)
            self.lbl_meta.setText("没有销售记录，无法生成报告。请先在「数据导入」页载入示例数据。")
            return

        inventory = schema.fetch_inventory()
        products = schema.fetch_products()
        categories = sorted(
            {row.get("category") or "" for row in products if row.get("category")}
        )
        config = schema.get_config()
        lead_time = int(float(config.get("lead_time_days", "3")))
        service_level = float(config.get("service_level", "0.95"))
        replenish_days = int(float(config.get("replenish_days", "7")))
        slow_days = int(float(config.get("slow_turnover_days", "45")))
        min_support = float(config.get("min_support", "0.010"))
        month = date.today().month
        days = sorted(
            str(row.get("ts") or row.get("date") or "")[:10]
            for row in records
            if str(row.get("ts") or row.get("date") or "")
        )
        period = f"{days[0]} 至 {days[-1]}" if days else "本期"

        self.btn_gen.setEnabled(False)
        self.btn_gen.setText("生成中…")
        client = get_client()
        provider_name = "第三方 API" if client.is_remote else "本地模型"
        style_pill(self.status, f"正在请求{provider_name}…", "blue")
        self.status.setVisible(True)
        timeout = client.request_timeout
        self.lbl_meta.setText(
            f"{provider_name}最长等待 {timeout} 秒；若不可用会立即切换为基础统计模式。"
        )

        def job():
            profiles = classify.analyze(records, inventory, slow_turnover_days=slow_days)
            suggestions = replenish.build_all_suggestions(
                records,
                inventory,
                lead_time_days=lead_time,
                service_level=service_level,
                replenish_days=replenish_days,
            )
            rules = basket.mine_rules(
                basket.build_baskets(records),
                min_support=min_support,
                min_confidence=0.3,
                only_positive=True,
            )
            if report_type == "weekly":
                payload, used = tasks.generate_report(
                    suggestions,
                    profiles,
                    rules,
                    period=period,
                    sample_size=len(records),
                )
            elif report_type == "slow":
                payload, used = tasks.analyze_slow_movers(profiles, days=90)
            elif report_type == "layout":
                payload, used = tasks.suggest_layout(rules)
            elif report_type == "seasonal":
                payload, used = tasks.recommend_seasonal(records, month, categories)
            else:
                payload, used = tasks.map_trend_to_sku(trend_text, categories)
            return report_type, payload, used, len(records), len(profiles)

        self._worker = FunctionWorker(job)
        self._worker.succeeded.connect(self._render)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def shutdown(self) -> None:
        from app.ui.worker import stop_worker

        stop_worker(self._worker)
        stop_worker(self._status_worker)

    # ==========================================================
    def _render(self, payload) -> None:
        report_type, result, used, sample_size, sku_count = payload
        self.btn_gen.setEnabled(True)
        self.btn_gen.setText("生成报告")

        if isinstance(result, list):
            if report_type == "slow":
                if result:
                    body = "\n".join(
                        f"· {item.get('sku_id')}：原因 {item.get('reason')}；"
                        f"建议 {item.get('action')}；{item.get('note', '')}"
                        for item in result
                    )
                else:
                    body = "本周期没有需要归因的滞销 / 呆滞商品。"
            else:
                if result:
                    body = "\n".join(
                        f"· {item.get('keyword')} → {item.get('category')}"
                        f"（置信度 {item.get('confidence', 0):.2f}）：{item.get('reason', '')}"
                        for item in result
                    )
                else:
                    body = "未从热点文本中识别出与店内品类相关的机会。"
        else:
            body = str(result or "").strip()
            if not body:
                body = "模型没有返回内容，已切换为基础统计模式。"

        if not used and "基础统计模式" not in body:
            body = prompts.DEGRADED_NOTICE + "\n\n" + body

        footer = (
            f"\n\n———\n"
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"分析样本：{sample_size} 条销售记录 / {sku_count} 个 SKU\n"
            f"报告类型：{REPORT_LABELS.get(report_type, report_type)}\n"
            "本结果仅为经营辅助建议，请结合门店实际情况判断。"
        )
        full_text = body + footer
        self.text.setPlainText(full_text)
        self._last_report = (report_type, full_text, sample_size)
        self.btn_save.setEnabled(True)

        client = get_client()
        provider_name = "第三方 API" if client.is_remote else "本地模型"
        if used:
            style_pill(self.status, f"生成完成 · {provider_name}", "green")
            self.banner.setVisible(False)
        else:
            style_pill(self.status, "生成完成 · 基础统计模式", "amber")
            self.banner.setText(
                f"{provider_name}当前不可用，报告已由算法结果 + 模板自动兜底生成；"
                "库存、补货、分类等计算不受影响。"
            )
            self.banner.setVisible(True)
        self.status.setVisible(True)
        self.lbl_meta.setText(
            f"本次使用 {sample_size} 条销售记录、{sku_count} 个 SKU；"
            "所有数字均由算法层计算，模型只负责文字解读。"
        )

    def _failed(self, message: str) -> None:
        self.btn_gen.setEnabled(True)
        self.btn_gen.setText("生成报告")
        style_pill(self.status, "生成失败", "red")
        self.status.setVisible(True)
        self.lbl_meta.setText(message)
        client = get_client()
        provider_name = "第三方 API" if client.is_remote else "Ollama"
        self.banner.setText(
            f"报告生成过程中出现异常，算法统计功能不受影响。请检查{provider_name}配置，"
            "或直接查看「库存与补货」页的表格结果。"
        )
        self.banner.setVisible(True)

    # ==========================================================
    def _save(self) -> None:
        if not self._last_report:
            return
        report_type, content, sample_size = self._last_report
        client = get_client()
        params = json.dumps(
            {
                "generated_by": client.provider,
                "app": "SmartWMS",
                "version": "1.0.2",
            },
            ensure_ascii=False,
        )
        try:
            schema.save_report(report_type, content, sample_size=sample_size, params=params)
        except Exception as exc:
            style_pill(self.status, "保存失败", "red")
            self.status.setVisible(True)
            self.lbl_meta.setText(f"写入数据库失败：{exc}")
            return
        style_pill(self.status, "已保存到历史报告", "green")
        self.status.setVisible(True)
        self._refresh_history()

    def _refresh_history(self) -> None:
        try:
            reports = schema.fetch_reports(limit=30)
        except Exception:
            reports = []
        self.cb_history.blockSignals(True)
        self.cb_history.clear()
        self._history.clear()
        for report in reports:
            label = (
                f"{report['generated_at'][:16]} · "
                f"{REPORT_LABELS.get(report['report_type'], report['report_type'])}"
            )
            self.cb_history.addItem(label, report["report_id"])
            self._history[str(report["report_id"])] = (
                report["content"],
                report["sample_size"],
            )
        self.cb_history.blockSignals(False)

    def _load_history(self, *args) -> None:
        report_id = self.cb_history.currentData()
        if report_id is None:
            return
        item = self._history.get(str(report_id))
        if not item:
            return
        content, sample_size = item
        self.text.setPlainText(content)
        self._last_report = ("history", content, sample_size)
        self.btn_save.setEnabled(True)
        style_pill(self.status, "已载入历史报告", "blue")
        self.status.setVisible(True)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text.toPlainText())
        style_pill(self.status, "已复制到剪贴板", "blue")
        self.status.setVisible(True)

    def on_data_changed(self, source: str = "") -> None:
        style_pill(self.status, "数据已更新，可重新生成报告", "amber")
        self.status.setVisible(True)

    def on_show(self) -> None:
        if self._status_worker is not None and self._status_worker.isRunning():
            return
        self._check_status()

    def on_config_changed(self) -> None:
        if self._status_worker is not None and self._status_worker.isRunning():
            return
        self._check_status()
        style_pill(self.status, "模型配置已更新", "blue")
        self.status.setVisible(True)
