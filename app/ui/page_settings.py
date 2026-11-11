"""参数配置页。

对应需求：2.4.3 灵活性（业务参数可配置）
工作项：M9 参数配置界面、M11 数据备份

配置保存在 SQLite 的 config 表里，重启程序后自动回填；
保存后通过 config_changed 信号通知补货页和报告页重新计算。

模型来源支持两种：
    1. Ollama 本地模型（默认，数据不出本机）
    2. 第三方 OpenAI 兼容 API（显式开启，聚合摘要会发送到服务商）
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core import replenish
from app.db import schema
from app.llm.client import (
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    LLMClient,
    LLMConfig,
    apply_config,
)
from app.ui.base_page import WorkPage
from app.ui.helpers import hint_label, pill, style_pill
from app.ui.theme import COLORS
from app.ui.worker import FunctionWorker

MODEL_CHOICES = ["qwen3:4b", "qwen3:8b", "qwen3:1.7b", "qwen3:0.6b"]
DEFAULT_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_API_MODEL = "deepseek-chat"


class SettingsPage(WorkPage):
    config_changed = Signal()

    def __init__(self):
        super().__init__(
            "参数配置",
            "业务参数与模型配置保存在本地 SQLite。默认使用本地 Ollama；"
            "只有显式选择第三方 API 时，聚合摘要才会发送到对应服务商。",
        )
        self.setWindowTitle("参数配置")
        self._model_worker: FunctionWorker | None = None
        self._probe_populate = False

        card = QWidget()
        card.setObjectName("Card")
        card.setStyleSheet(
            "QWidget#Card { background: #FFFFFF; border: 1px solid #E2DFD4;"
            " border-radius: 10px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 18, 22, 18)
        card_layout.setSpacing(10)

        title = QLabel("业务参数")
        title.setObjectName("SectionTitle")
        card_layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.sp_replenish_days = QSpinBox()
        self.sp_replenish_days.setRange(1, 365)
        self.sp_replenish_days.setSuffix(" 天")
        form.addRow("补货周期", self.sp_replenish_days)

        self.sp_lead_time = QSpinBox()
        self.sp_lead_time.setRange(0, 90)
        self.sp_lead_time.setSuffix(" 天")
        form.addRow("供应商到货提前期 LT", self.sp_lead_time)

        self.sp_service_level = QDoubleSpinBox()
        self.sp_service_level.setRange(0.50, 0.999)
        self.sp_service_level.setSingleStep(0.01)
        self.sp_service_level.setDecimals(3)
        form.addRow("服务水平（决定安全库存系数 z）", self.sp_service_level)

        self.sp_min_support = QDoubleSpinBox()
        self.sp_min_support.setRange(0.001, 1.0)
        self.sp_min_support.setSingleStep(0.005)
        self.sp_min_support.setDecimals(3)
        form.addRow("Apriori 最小支持度", self.sp_min_support)

        self.sp_slow_days = QSpinBox()
        self.sp_slow_days.setRange(7, 365)
        self.sp_slow_days.setSuffix(" 天")
        form.addRow("滞销判定周转天数阈值", self.sp_slow_days)

        self.cb_provider = QComboBox()
        self.cb_provider.addItem("Ollama 本地模型（数据不出本机）", PROVIDER_OLLAMA)
        self.cb_provider.addItem("第三方 OpenAI 兼容 API", PROVIDER_OPENAI)
        self.cb_provider.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("模型来源", self.cb_provider)

        self.cb_model = QComboBox()
        self.cb_model.setEditable(True)
        self.cb_model.addItems(MODEL_CHOICES)
        self.cb_model.setMinimumWidth(180)
        form.addRow("本地模型档位", self.cb_model)

        card_layout.addLayout(form)

        # ---------- 第三方 API 配置 ----------
        self.api_box = QWidget()
        self.api_box.setObjectName("ApiBox")
        self.api_box.setStyleSheet(
            "QWidget#ApiBox { background: #F8F7F2; border: 1px solid #E8E5DA;"
            " border-radius: 8px; }"
        )
        api_layout = QVBoxLayout(self.api_box)
        api_layout.setContentsMargins(14, 12, 14, 12)
        api_layout.setSpacing(8)

        api_title = QLabel("第三方 OpenAI 兼容 API")
        api_title.setObjectName("SectionTitle")
        api_layout.addWidget(api_title)

        api_form = QFormLayout()
        api_form.setSpacing(10)
        api_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.ed_api_base = QLineEdit()
        self.ed_api_base.setPlaceholderText("https://api.deepseek.com/v1")
        api_form.addRow("Base URL", self.ed_api_base)

        self.cb_api_model = QComboBox()
        self.cb_api_model.setEditable(True)
        self.cb_api_model.setMinimumWidth(220)
        self.cb_api_model.addItems(
            ["deepseek-chat", "qwen-plus", "gpt-4o-mini", "moonshot-v1-8k"]
        )
        api_form.addRow("API 模型名", self.cb_api_model)

        self.ed_api_key = QLineEdit()
        self.ed_api_key.setEchoMode(QLineEdit.Password)
        self.ed_api_key.setPlaceholderText("sk-...（可留空，改用环境变量 SMARTWMS_API_KEY）")
        api_form.addRow("API Key", self.ed_api_key)

        self.sp_api_timeout = QSpinBox()
        self.sp_api_timeout.setRange(10, 300)
        self.sp_api_timeout.setSuffix(" 秒")
        self.sp_api_timeout.setValue(60)
        api_form.addRow("请求超时", self.sp_api_timeout)

        probe_row = QWidget()
        probe_layout = QHBoxLayout(probe_row)
        probe_layout.setContentsMargins(0, 0, 0, 0)
        probe_layout.setSpacing(8)
        self.btn_test = QPushButton("测试连接")
        self.btn_test.setProperty("variant", "ghost")
        self.btn_test.clicked.connect(self._test_connection)
        probe_layout.addWidget(self.btn_test)
        self.lbl_api_status = hint_label("")
        probe_layout.addWidget(self.lbl_api_status, 1)
        api_form.addRow("", probe_row)

        api_layout.addLayout(api_form)

        self.lbl_api_note = hint_label(
            "隐私提示：第三方 API 只接收聚合后的统计摘要（SKU 数、销售额、补货行等），"
            "不上传原始 CSV。API Key 会明文保存在本机 SQLite；公用电脑建议使用环境变量 "
            "SMARTWMS_API_KEY 覆盖。"
        )
        self.lbl_api_note.setStyleSheet(f"color: {COLORS['amber']}; font-size: 11px;")
        self.lbl_api_note.setWordWrap(True)
        api_layout.addWidget(self.lbl_api_note)

        card_layout.addWidget(self.api_box)

        self.lbl_hint = hint_label("")
        self.lbl_hint.setStyleSheet(f"color: {COLORS['muted']}; font-size: 12px;")
        card_layout.addWidget(self.lbl_hint)

        self.body.addWidget(card)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_save = QPushButton("保存配置")
        self.btn_restore = QPushButton("恢复默认")
        self.btn_restore.setProperty("variant", "ghost")
        self.btn_models = QPushButton("刷新模型列表")
        self.btn_models.setProperty("variant", "ghost")
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_restore)
        actions.addWidget(self.btn_models)
        actions.addStretch(1)
        self.status = pill("尚未修改", "blue")
        self.status.setVisible(False)
        actions.addWidget(self.status)
        self.body.addLayout(actions)

        backup_row = QHBoxLayout()
        backup_row.setSpacing(8)
        self.btn_backup = QPushButton("备份数据库")
        self.btn_backup.setProperty("variant", "ghost")
        self.btn_dir = QPushButton("打开数据目录")
        self.btn_dir.setProperty("variant", "ghost")
        backup_row.addWidget(self.btn_backup)
        backup_row.addWidget(self.btn_dir)
        backup_row.addStretch(1)
        self.body.addLayout(backup_row)

        self.lbl_stats = hint_label("正在读取数据库统计…")
        self.body.addWidget(self.lbl_stats)
        self.body.addStretch(1)

        self.btn_save.clicked.connect(self._save)
        self.btn_restore.clicked.connect(self._restore)
        self.btn_models.clicked.connect(lambda: self._run_probe(populate=True))
        self.btn_backup.clicked.connect(self._backup)
        self.btn_dir.clicked.connect(self._open_dir)
        self.sp_service_level.valueChanged.connect(self._update_hint)

        self._load_config()
        self._refresh_stats()

    # ==========================================================
    # 配置读写
    # ==========================================================
    def _load_config(self) -> None:
        try:
            config = schema.get_config()
        except Exception:
            config = dict(schema.DEFAULT_CONFIG)

        self.sp_replenish_days.setValue(int(float(config.get("replenish_days", 7))))
        self.sp_lead_time.setValue(int(float(config.get("lead_time_days", 3))))
        self.sp_service_level.setValue(float(config.get("service_level", 0.95)))
        self.sp_min_support.setValue(float(config.get("min_support", 0.010)))
        self.sp_slow_days.setValue(int(float(config.get("slow_turnover_days", 45))))

        provider = str(config.get("llm_provider", PROVIDER_OLLAMA))
        index = self.cb_provider.findData(provider)
        self.cb_provider.setCurrentIndex(index if index >= 0 else 0)

        model = config.get("model", "qwen3:4b")
        if model:
            idx = self.cb_model.findText(model)
            if idx >= 0:
                self.cb_model.setCurrentIndex(idx)
            else:
                self.cb_model.setEditText(model)

        self.ed_api_base.setText(str(config.get("api_base_url", DEFAULT_API_BASE)))
        self.cb_api_model.setCurrentText(str(config.get("api_model", DEFAULT_API_MODEL)))
        self.ed_api_key.setText(str(config.get("api_key", "")))
        try:
            self.sp_api_timeout.setValue(int(float(config.get("api_timeout", 60))))
        except (TypeError, ValueError):
            self.sp_api_timeout.setValue(60)

        self._on_provider_changed()
        self._update_hint()

    def _on_provider_changed(self, *args) -> None:
        is_api = self.cb_provider.currentData() == PROVIDER_OPENAI
        self.api_box.setVisible(is_api)
        if is_api:
            self.lbl_hint.setText(
                "已选择第三方 API：报告生成会把聚合摘要发送到填写的服务商；"
                "库存、补货、分类仍在本机计算。"
            )
        else:
            self._update_hint()

    def _update_hint(self) -> None:
        if self.cb_provider.currentData() == PROVIDER_OPENAI:
            return
        try:
            z = replenish.z_for(self.sp_service_level.value())
        except Exception:
            z = 1.65
        self.lbl_hint.setText(
            f"当前服务水平对应安全库存系数 z = {z:.2f}。"
            " 补货量 = 日均销量 ×（到货提前期 + 补货周期）+ 安全库存 − 现有库存。"
        )

    def _config_from_form(self) -> LLMConfig:
        return LLMConfig(
            model=self.cb_model.currentText().strip() or "qwen3:4b",
            provider=self.cb_provider.currentData() or PROVIDER_OLLAMA,
            api_base_url=self.ed_api_base.text().strip(),
            api_model=self.cb_api_model.currentText().strip(),
            api_key=self.ed_api_key.text().strip(),
            api_timeout=self.sp_api_timeout.value(),
        )

    def _save(self) -> None:
        provider = self.cb_provider.currentData()
        if provider == PROVIDER_OPENAI:
            if not self.ed_api_base.text().strip():
                style_pill(self.status, "请填写 API Base URL", "red")
                self.status.setVisible(True)
                return
            if not self.cb_api_model.currentText().strip():
                style_pill(self.status, "请填写 API 模型名", "red")
                self.status.setVisible(True)
                return

        try:
            current = schema.get_config()
        except Exception:
            current = dict(schema.DEFAULT_CONFIG)
        values = {
            "replenish_days": str(self.sp_replenish_days.value()),
            "lead_time_days": str(self.sp_lead_time.value()),
            "service_level": f"{self.sp_service_level.value():.3f}",
            "min_support": f"{self.sp_min_support.value():.3f}",
            "slow_turnover_days": str(self.sp_slow_days.value()),
            "model": self.cb_model.currentText().strip() or "qwen3:4b",
            "ollama_base_url": current.get(
                "ollama_base_url", schema.DEFAULT_CONFIG["ollama_base_url"]
            ),
            "llm_provider": provider,
            "api_base_url": self.ed_api_base.text().strip(),
            "api_model": self.cb_api_model.currentText().strip(),
            "api_key": self.ed_api_key.text().strip(),
            "api_timeout": str(self.sp_api_timeout.value()),
        }
        try:
            schema.set_configs(values)
            apply_config(schema.get_config())
        except Exception as exc:
            style_pill(self.status, "保存失败", "red")
            self.status.setVisible(True)
            self.lbl_stats.setText(f"写入配置失败：{exc}")
            return

        if provider == PROVIDER_OPENAI and not (
            self.ed_api_key.text().strip() or os.environ.get("SMARTWMS_API_KEY")
        ):
            style_pill(self.status, "已保存，但未填 API Key", "amber")
        else:
            style_pill(self.status, f"已保存 · {datetime.now().strftime('%H:%M:%S')}", "green")
        self.status.setVisible(True)
        self._update_hint()
        self.config_changed.emit()

    def _restore(self) -> None:
        defaults = schema.DEFAULT_CONFIG
        self.sp_replenish_days.setValue(int(defaults["replenish_days"]))
        self.sp_lead_time.setValue(int(defaults["lead_time_days"]))
        self.sp_service_level.setValue(float(defaults["service_level"]))
        self.sp_min_support.setValue(float(defaults["min_support"]))
        self.sp_slow_days.setValue(int(defaults["slow_turnover_days"]))

        index = self.cb_provider.findData(defaults["llm_provider"])
        self.cb_provider.setCurrentIndex(index if index >= 0 else 0)

        index = self.cb_model.findText(defaults["model"])
        if index >= 0:
            self.cb_model.setCurrentIndex(index)
        else:
            self.cb_model.setEditText(defaults["model"])

        self.ed_api_base.setText(defaults["api_base_url"])
        self.cb_api_model.setCurrentText(defaults["api_model"])
        self.ed_api_key.setText(defaults["api_key"])
        self.sp_api_timeout.setValue(int(defaults["api_timeout"]))
        self._on_provider_changed()
        style_pill(self.status, "已恢复默认值，记得点击保存", "amber")
        self.status.setVisible(True)

    # ==========================================================
    # 连接探测
    # ==========================================================
    def _run_probe(self, populate: bool = False) -> None:
        if self._model_worker is not None and self._model_worker.isRunning():
            return
        self._probe_populate = populate
        style_pill(self.status, "正在读取模型列表…", "blue")
        self.status.setVisible(True)
        self.lbl_api_status.setText("正在连接…")

        client = LLMClient(self._config_from_form())

        def job():
            available = client.is_available()
            models = client.list_models() if available else []
            return client, available, models

        self._model_worker = FunctionWorker(job)
        self._model_worker.succeeded.connect(self._apply_probe)
        self._model_worker.failed.connect(self._probe_failed)
        self._model_worker.start()

    def _test_connection(self) -> None:
        self._run_probe(populate=False)

    def shutdown(self) -> None:
        from app.ui.worker import stop_worker

        stop_worker(self._model_worker)

    def _apply_probe(self, result) -> None:
        client, available, models = result
        if available:
            style_pill(self.status, f"{client.provider_label} 在线", "green")
            if client.is_remote:
                current = self.cb_api_model.currentText().strip()
                if models and self._probe_populate:
                    self.cb_api_model.blockSignals(True)
                    self.cb_api_model.clear()
                    self.cb_api_model.addItems(models)
                    idx = self.cb_api_model.findText(current)
                    if idx >= 0:
                        self.cb_api_model.setCurrentIndex(idx)
                    else:
                        self.cb_api_model.setCurrentText(current or models[0])
                    self.cb_api_model.blockSignals(False)
                detail = "、".join(models[:8]) if models else "该接口未返回模型列表"
                self.lbl_api_status.setText(f"连接成功　可用模型：{detail}")
                self.lbl_stats.setText(
                    f"第三方 API：{client.config.api_base_url}　模型：{client.config.api_model}"
                )
            else:
                current = self.cb_model.currentText().strip()
                choices = list(dict.fromkeys(MODEL_CHOICES + list(models)))
                if self._probe_populate:
                    self.cb_model.blockSignals(True)
                    self.cb_model.clear()
                    self.cb_model.addItems(choices)
                    idx = self.cb_model.findText(current)
                    if idx >= 0:
                        self.cb_model.setCurrentIndex(idx)
                    else:
                        self.cb_model.setEditText(current)
                    self.cb_model.blockSignals(False)
                self.lbl_api_status.setText(
                    "本地模型：" + ("、".join(models) if models else "未检测到模型")
                )
                self.lbl_stats.setText(
                    "已安装模型：" + ("、".join(models) if models else "无")
                    + "　（下拉框可手动输入其他模型名）"
                )
        else:
            style_pill(self.status, "连接失败", "amber")
            reason = client.degrade_reason()
            self.lbl_api_status.setText(reason)
            self.lbl_stats.setText(reason)
        self.status.setVisible(True)

    def _probe_failed(self, message: str) -> None:
        style_pill(self.status, "读取模型失败", "red")
        self.status.setVisible(True)
        self.lbl_api_status.setText(message)
        self.lbl_stats.setText(message)

    # ==========================================================
    # 备份与统计
    # ==========================================================
    def _backup(self) -> None:
        default = Path(schema.DB_PATH).parent / (
            f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "备份数据库", str(default), "SQLite 数据库 (*.db);;所有文件 (*)"
        )
        if not path:
            return
        try:
            target = schema.backup_to(Path(path))
        except Exception as exc:
            style_pill(self.status, "备份失败", "red")
            self.status.setVisible(True)
            self.lbl_stats.setText(f"备份失败：{exc}")
            return
        style_pill(self.status, "备份完成", "green")
        self.status.setVisible(True)
        self.lbl_stats.setText(f"数据库已备份到：{target}")

    def _open_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(schema.DB_PATH).parent)))

    def _refresh_stats(self) -> None:
        try:
            stats = schema.db_stats()
            self.lbl_stats.setText(
                f"数据库：{stats['size_mb']} MB　销售明细 {stats['transaction_items']:,} 行　"
                f"商品 {stats['products']:,} 个　跨度 {stats['span_days']} 天　"
                f"路径：{schema.DB_PATH}"
            )
        except Exception as exc:
            self.lbl_stats.setText(f"读取数据库统计失败：{exc}")

    def on_show(self) -> None:
        self._refresh_stats()
