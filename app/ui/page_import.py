"""数据导入页。

对应需求：2.2.1 数据输入一般性规定、2.4.4 输入输出要求
工作项：M1 数据导入与校验

流程：
    选择文件 → 自动识别编码 → 校验字段与数值 → 展示错误行号 →
    校验通过后写入 SQLite → 通知其他页面刷新。

原始文件永远只读，系统只在 data/app.db 里写数据。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QTableWidget,
)

from app.core import ingest
from app.db import schema
from app.paths import sample_dir
from app.ui.base_page import WorkPage
from app.ui.helpers import fill_table, hint_label, pill, setup_table, style_pill
from app.ui.theme import COLORS

SAMPLE_DIR = sample_dir()

PREVIEW_COLUMNS = {
    "receipt": [
        ("order_id", "订单号"),
        ("sku_id", "SKU"),
        ("qty", "数量"),
        ("date", "交易时间"),
        ("unit_price", "单价"),
    ],
    "inventory": [
        ("sku_id", "SKU"),
        ("sku_name", "商品名称"),
        ("stock_qty", "现有库存"),
        ("cost", "进货成本"),
        ("snapshot_date", "快照日期"),
    ],
    "products": [
        ("sku_id", "SKU"),
        ("sku_name", "商品名称"),
        ("category", "品类"),
        ("cost", "成本"),
        ("price", "售价"),
    ],
}


class ImportPage(WorkPage):
    data_imported = Signal(str)

    def __init__(self):
        super().__init__(
            "数据导入",
            "支持购物小票（CSV / TXT）、库存数据与商品档案导入。原始文件只读，"
            "系统不会修改；校验不通过的文件会被拒绝，并给出具体行号。",
        )
        self.setWindowTitle("数据导入")
        self._pending_kind: str | None = None
        self._pending_rows: list[dict] = []
        self._pending_path: str = ""

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_receipt = QPushButton("选择小票文件")
        self.btn_inventory = QPushButton("选择库存文件")
        self.btn_products = QPushButton("选择商品档案")
        for button in (self.btn_receipt, self.btn_inventory, self.btn_products):
            button.setProperty("variant", "ghost")
            row.addWidget(button)
        row.addStretch(1)
        self.btn_sample = QPushButton("一键载入示例数据")
        row.addWidget(self.btn_sample)
        self.body.addLayout(row)

        self.btn_receipt.clicked.connect(lambda: self._choose("receipt"))
        self.btn_inventory.clicked.connect(lambda: self._choose("inventory"))
        self.btn_products.clicked.connect(lambda: self._choose("products"))
        self.btn_sample.clicked.connect(self._load_sample)

        self.lbl_info = hint_label("尚未选择文件")
        self.body.addWidget(self.lbl_info)

        status_row = QHBoxLayout()
        self.status = pill("等待导入", "green")
        self.status.setVisible(False)
        status_row.addWidget(self.status)
        self.lbl_warn = hint_label("")
        self.lbl_warn.setStyleSheet(f"color: {COLORS['amber']}; font-size: 12px;")
        status_row.addWidget(self.lbl_warn, 1)
        self.body.addLayout(status_row)

        self.error_list = QListWidget()
        self.error_list.setVisible(False)
        self.error_list.setMaximumHeight(118)
        self.error_list.setStyleSheet(
            f"QListWidget {{ background: {COLORS['red_soft']}; border: 1px solid #E9C5C5;"
            f" border-radius: 8px; color: {COLORS['red']}; padding: 4px; font-size: 12px; }}"
        )
        self.body.addWidget(self.error_list)

        self.table = QTableWidget()
        self.table.setMinimumHeight(260)
        setup_table(self.table, ["预览"])
        self.body.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.lbl_preview = hint_label("校验通过后，这里会显示前 50 行预览")
        bottom.addWidget(self.lbl_preview, 1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setProperty("variant", "ghost")
        self.btn_cancel.setEnabled(False)
        self.btn_confirm = QPushButton("确认导入")
        self.btn_confirm.setEnabled(False)
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_confirm)
        self.body.addLayout(bottom)

        self.btn_confirm.clicked.connect(self._confirm)
        self.btn_cancel.clicked.connect(self._clear_pending)
        self.refresh()

    # ==========================================================
    # 文件选择与校验
    # ==========================================================
    def _choose(self, kind: str) -> None:
        label = {"receipt": "购物小票", "inventory": "库存数据", "products": "商品档案"}[kind]
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择{label}文件", str(SAMPLE_DIR), "数据文件 (*.csv *.txt);;所有文件 (*)"
        )
        if path:
            self._validate(kind, path)

    def _validate(self, kind: str, path: str) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            encoding = ingest.sniff_encoding(path)
            if kind == "receipt":
                result = ingest.validate_receipt(path)
            elif kind == "inventory":
                result = ingest.validate_inventory(path)
            else:
                result = ingest.validate_products(path)
        except Exception as exc:  # 读取失败要让用户看到原因，不能崩
            QApplication.restoreOverrideCursor()
            self._set_error(f"读取失败：{exc}")
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

        kind_name = {"receipt": "小票", "inventory": "库存", "products": "商品档案"}[kind]
        file_name = Path(path).name
        self.lbl_info.setText(
            f"{kind_name}文件：{file_name}　编码：{encoding}　"
            f"合格 {len(result.rows)} 行　共 {len(result.rows) + len(result.errors)} 行记录"
            f"　路径：{path}"
        )

        self.error_list.clear()
        if result.errors:
            self.error_list.setVisible(True)
            for message in result.errors[:40]:
                self.error_list.addItem(message)
            if len(result.errors) > 40:
                self.error_list.addItem(f"…… 还有 {len(result.errors) - 40} 处错误未显示")
        else:
            self.error_list.setVisible(False)

        self.lbl_warn.setText("；".join(result.warnings[:3]) if result.warnings else "")

        if result.ok:
            style_pill(self.status, f"校验通过 · {len(result.rows)} 行", "green")
            self.status.setVisible(True)
            self._pending_kind = kind
            self._pending_rows = result.rows
            self._pending_path = path
            self.btn_confirm.setEnabled(True)
            self.btn_cancel.setEnabled(True)
            self._preview(kind, result.rows)
        else:
            style_pill(self.status, f"校验未通过 · {len(result.errors)} 处错误", "red")
            self.status.setVisible(True)
            self._clear_pending(keep_status=True)
            self.status.setVisible(True)
            if result.rows:
                self._preview(kind, result.rows)

    def _preview(self, kind: str, rows: list[dict]) -> None:
        columns = PREVIEW_COLUMNS[kind]
        setup_table(self.table, [title for _, title in columns])
        widths = {
            "receipt": {0: 110, 1: 100, 2: 80, 3: 185, 4: 90},
            "inventory": {0: 110, 1: 160, 2: 100, 3: 100, 4: 110},
            "products": {0: 110, 1: 170, 2: 110, 3: 90, 4: 90},
        }[kind]
        for index, width in widths.items():
            if index < len(columns):
                self.table.setColumnWidth(index, width)
        preview_rows = [
            [row.get(key, "") for key, _ in columns] for row in rows[:50]
        ]
        numeric = {"receipt": {2, 4}, "inventory": {2, 3}, "products": {3, 4}}[kind]
        fill_table(self.table, preview_rows, numeric_columns=numeric)
        self.lbl_preview.setText(
            f"预览前 {min(50, len(rows))} 行 / 共 {len(rows)} 行合格数据"
        )

    # ==========================================================
    # 入库
    # ==========================================================
    def _confirm(self) -> None:
        if not self._pending_kind or not self._pending_rows:
            return
        kind = self._pending_kind
        rows = self._pending_rows
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            schema.init_db()
            sku_ids = sorted({str(row["sku_id"]) for row in rows})
            if kind == "receipt":
                schema.ensure_products(sku_ids)
                count = schema.insert_sales(rows)
                message = f"已导入 {count} 条销售明细，涉及 {len(sku_ids)} 个 SKU"
            elif kind == "inventory":
                schema.ensure_products(sku_ids)
                count = schema.insert_inventory(rows)
                message = f"已导入 {count} 个 SKU 的库存快照"
            else:
                count = schema.insert_products(rows)
                message = f"已导入 {count} 个商品档案"
            schema.analyze()
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._set_error(f"写入数据库失败：{exc}")
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

        self.lbl_info.setText(message)
        style_pill(self.status, "导入成功", "green")
        self.status.setVisible(True)
        self.lbl_warn.setText("原始文件未被修改；数据已写入 data/app.db")
        self._clear_pending(keep_status=True)
        self.status.setVisible(True)
        self.data_imported.emit(kind)
        self.refresh()

    def _load_sample(self) -> None:
        """一键载入 data/sample 下的 30 个 SKU / 120 天示例数据。"""
        paths = {
            "products": SAMPLE_DIR / "products.csv",
            "receipt": SAMPLE_DIR / "receipts.csv",
            "inventory": SAMPLE_DIR / "inventory.csv",
        }
        missing = [path.name for path in paths.values() if not path.exists()]
        if missing:
            self._set_error(
                f"缺少示例文件：{'、'.join(missing)}。请先运行 python tools/make_fake_data.py"
            )
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            schema.init_db()
            products = ingest.validate_products(paths["products"])
            receipts = ingest.validate_receipt(paths["receipt"])
            inventory = ingest.validate_inventory(paths["inventory"])
            if not (products.ok and receipts.ok and inventory.ok):
                raise RuntimeError(
                    "示例数据校验失败：" + "；".join(
                        (products.errors + receipts.errors + inventory.errors)[:3]
                    )
                )
            schema.insert_products(products.rows)
            schema.insert_sales(receipts.rows)
            schema.insert_inventory(inventory.rows)
            schema.analyze()
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._set_error(f"载入示例数据失败：{exc}")
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

        self.lbl_info.setText(
            f"示例数据已载入：{len(receipts.rows)} 条销售明细、"
            f"{len(products.rows)} 个 SKU、{len(inventory.rows)} 条库存快照"
        )
        style_pill(self.status, "示例数据就绪", "green")
        self.status.setVisible(True)
        self.lbl_warn.setText("现在可以到「购物篮分析」「库存与补货」页面查看结果")
        self._preview("receipt", receipts.rows)
        self._clear_pending(keep_status=True)
        self.status.setVisible(True)
        self.data_imported.emit("sample")
        self.refresh()

    # ==========================================================
    # 辅助
    # ==========================================================
    def _clear_pending(self, keep_status: bool = False) -> None:
        self._pending_kind = None
        self._pending_rows = []
        self._pending_path = ""
        self.btn_confirm.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        if not keep_status:
            self.status.setVisible(False)
            self.lbl_info.setText("尚未选择文件")

    def _set_error(self, message: str) -> None:
        self.error_list.clear()
        self.error_list.addItem(message)
        self.error_list.setVisible(True)
        style_pill(self.status, "操作失败", "red")
        self.status.setVisible(True)

    def refresh(self) -> None:
        """刷新数据库概况（主窗口在导入后也会调用）。"""
        try:
            stats = schema.db_stats()
            self.lbl_info.setToolTip(
                f"数据库 {stats['size_mb']} MB，明细 {stats['transaction_items']} 行，"
                f"跨度 {stats['span_days']} 天"
            )
        except Exception:
            pass

    def on_data_changed(self, source: str = "") -> None:
        self.refresh()
