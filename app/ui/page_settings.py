"""参数配置页。

对应需求：2.4.3 灵活性（业务参数可配置）
工作项：M9 参数配置界面、M11 数据备份

配置保存在 SQLite 的 config 表里，重启程序后自动回填；
保存后通过 config_changed 信号通知补货页和报告页重新计算。
"""

from __future__ import annotations

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
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core import replenish
from app.db import schema
from app.llm.client import get_client
from app.ui.base_page import WorkPage
from app.ui.helpers import hint_label, pill, style_pill
from app.ui.theme import COLORS
from app.ui.worker import FunctionWorker

MODEL_CHOICES = ["qwen3:4b", "qwen3:8b", "qwen3:1.7b", "qwen3:0.6b"]


class SettingsPage(WorkPage):
    config_changed = Signal()

    def __init__(self):
        super().__init__(
            "参数配置",
            "按店铺实际经营情况调整业务参数，保存后参与后续运算。"
            "所有参数保存在本地 SQLite 中，不会上传到任何服务器。",
        )
        self.setWindowTitle("参数配置")
        self._model_worker: FunctionWorker | None = None

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

        self.cb_model = QComboBox()
        self.cb_model.setEditable(True)
        self.cb_model.addItems(MODEL_CHOICES)
        self.cb_model.setMinimumWidth(180)
        form.addRow("本地模型档位", self.cb_model)

        card_layout.addLayout(form)

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
        self.btn_models.clicked.connect(self._refresh_models)
        self.btn_backup.clicked.connect(self._backup)
        self.btn_dir.clicked.connect(self._open_dir)
        self.sp_service_level.valueChanged.connect(self._update_hint)

        self._load_config()
        self._refresh_stats()

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
        model = config.get("model", "qwen3:4b")
        if model:
            index = self.cb_model.findText(model)
            if index >= 0:
                self.cb_model.setCurrentIndex(index)
            else:
                self.cb_model.setEditText(model)
        self._update_hint()

    def _update_hint(self) -> None:
        try:
            z = replenish.z_for(self.sp_service_level.value())
        except Exception:
            z = 1.65
        self.lbl_hint.setText(
            f"当前服务水平对应安全库存系数 z = {z:.2f}。"
            " 补货量 = 日均销量 ×（到货提前期 + 补货周期）+ 安全库存 − 现有库存。"
        )

    def _save(self) -> None:
        values = {
            "replenish_days": str(self.sp_replenish_days.value()),
            "lead_time_days": str(self.sp_lead_time.value()),
            "service_level": f"{self.sp_service_level.value():.3f}",
            "min_support": f"{self.sp_min_support.value():.3f}",
            "slow_turnover_days": str(self.sp_slow_days.value()),
            "model": self.cb_model.currentText().strip() or "qwen3:4b",
        }
        try:
            schema.set_configs(values)
            get_client().config.model = values["model"]
        except Exception as exc:
            style_pill(self.status, "保存失败", "red")
            self.status.setVisible(True)
            self.lbl_stats.setText(f"写入配置失败：{exc}")
            return
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
        index = self.cb_model.findText(defaults["model"])
        if index >= 0:
            self.cb_model.setCurrentIndex(index)
        else:
            self.cb_model.setEditText(defaults["model"])
        style_pill(self.status, "已恢复默认值，记得点击保存", "amber")
        self.status.setVisible(True)

    def _refresh_models(self) -> None:
        if self._model_worker is not None and self._model_worker.isRunning():
            return
        style_pill(self.status, "正在读取已安装模型…", "blue")
        self.status.setVisible(True)

        def job():
            client = get_client()
            return client.is_available(), client.list_models()

        self._model_worker = FunctionWorker(job)
        self._model_worker.succeeded.connect(self._apply_models)
        self._model_worker.failed.connect(self._models_failed)
        self._model_worker.start()

    def shutdown(self) -> None:
        from app.ui.worker import stop_worker

        stop_worker(self._model_worker)

    def _apply_models(self, result) -> None:
        available, models = result
        current = self.cb_model.currentText().strip()
        choices = list(dict.fromkeys(MODEL_CHOICES + list(models)))
        self.cb_model.blockSignals(True)
        self.cb_model.clear()
        self.cb_model.addItems(choices)
        index = self.cb_model.findText(current)
        if index >= 0:
            self.cb_model.setCurrentIndex(index)
        else:
            self.cb_model.setEditText(current)
        self.cb_model.blockSignals(False)
        if available:
            style_pill(self.status, f"模型服务在线 · 已安装 {len(models)} 个", "green")
            self.lbl_stats.setText(
                "已安装模型：" + ("、".join(models) if models else "无")
                + "　（下拉框可手动输入其他模型名）"
            )
        else:
            style_pill(self.status, "Ollama 未启动", "amber")
            self.lbl_stats.setText(
                "没有连接上本地 Ollama 服务。程序仍可运行，报告页会自动降级为基础统计模式。"
            )
        self.status.setVisible(True)

    def _models_failed(self, message: str) -> None:
        style_pill(self.status, "读取模型失败", "red")
        self.status.setVisible(True)
        self.lbl_stats.setText(message)

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
