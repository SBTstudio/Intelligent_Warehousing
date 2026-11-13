"""实时库存 / 收银辅助页。

营业过程中使用：
    · 新增/编辑商品档案（名称、进价、售价、当前库存）
    · 表格里直接「卖出 1」「补货 1」，库存与销售流水同步更新
    · 顶部输入框支持手动 / 条形码 / NFC，预留了扫码解析接口
    · 所有变动带时间戳写入 inventory_events
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QWidget,
)

from app.core import realtime
from app.ui.base_page import WorkPage
from app.ui.helpers import fill_table, hint_label, pill, setup_table, style_pill

SOURCE_CHOICES = [
    ("手动", realtime.SOURCE_MANUAL),
    ("条形码", realtime.SOURCE_BARCODE),
    ("NFC", realtime.SOURCE_NFC),
]

ACTION_COLORS = {
    realtime.ACTION_SALE: ("#FCEBEB", "#8C2222"),
    realtime.ACTION_RESTOCK: ("#E1F5EE", "#0B5542"),
    realtime.ACTION_CREATE: ("#E8F0FB", "#2F5EA8"),
    realtime.ACTION_ADJUST: ("#FAEEDA", "#6B3F0A"),
}


class RealtimePage(WorkPage):
    data_changed = Signal(str)

    def __init__(self):
        super().__init__(
            "实时库存",
            "营业过程中直接维护商品与库存：新增商品、卖出减 1、补货加 N，"
            "每次变动都会记录精确到秒的时间戳和销售流水。",
        )
        self.setWindowTitle("实时库存")
        self._all_inventory: list[dict] = []
        self._stock_touched = False

        # ---------------- 商品档案表单 ----------------
        card = QWidget()
        card.setObjectName("Card")
        card.setStyleSheet(
            "QWidget#Card { background: #FFFFFF; border: 1px solid #E2DFD4;"
            " border-radius: 10px; }"
        )
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 14, 18, 14)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        title = QLabel("新增 / 编辑商品")
        title.setObjectName("SectionTitle")
        grid.addWidget(title, 0, 0, 1, 6)

        self.ed_sku = QLineEdit()
        self.ed_sku.setPlaceholderText("商品编号，如 S031")
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("商品名称")
        self.ed_category = QLineEdit()
        self.ed_category.setPlaceholderText("品类，如 饮料")

        self.sp_cost = QDoubleSpinBox()
        self.sp_cost.setRange(0, 999999)
        self.sp_cost.setDecimals(2)
        self.sp_cost.setPrefix("¥ ")
        self.sp_price = QDoubleSpinBox()
        self.sp_price.setRange(0, 999999)
        self.sp_price.setDecimals(2)
        self.sp_price.setPrefix("¥ ")
        self.sp_stock = QDoubleSpinBox()
        self.sp_stock.setRange(0, 9999999)
        self.sp_stock.setDecimals(2)

        grid.addWidget(QLabel("商品编号"), 1, 0)
        grid.addWidget(self.ed_sku, 1, 1)
        grid.addWidget(QLabel("商品名称"), 1, 2)
        grid.addWidget(self.ed_name, 1, 3)
        grid.addWidget(QLabel("品类"), 1, 4)
        grid.addWidget(self.ed_category, 1, 5)

        grid.addWidget(QLabel("进价"), 2, 0)
        grid.addWidget(self.sp_cost, 2, 1)
        grid.addWidget(QLabel("售价"), 2, 2)
        grid.addWidget(self.sp_price, 2, 3)
        grid.addWidget(QLabel("库存"), 2, 4)
        grid.addWidget(self.sp_stock, 2, 5)

        self.btn_save = QPushButton("保存 / 更新商品")
        self.btn_load = QPushButton("载入选中商品")
        self.btn_load.setProperty("variant", "ghost")
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setProperty("variant", "ghost")
        grid.addWidget(self.btn_save, 3, 0, 1, 2)
        grid.addWidget(self.btn_load, 3, 2, 1, 2)
        grid.addWidget(self.btn_clear, 3, 4, 1, 2)
        self.body.addWidget(card)

        # ---------------- 快速卖出 / 补货 ----------------
        quick = QHBoxLayout()
        quick.setSpacing(8)
        quick.addWidget(QLabel("扫码 / 手输"))
        self.ed_code = QLineEdit()
        self.ed_code.setPlaceholderText("输入 SKU、商品名或条形码；以后可接条码枪 / NFC")
        self.ed_code.setMinimumWidth(260)
        quick.addWidget(self.ed_code, 1)
        self.cb_source = QComboBox()
        for label, value in SOURCE_CHOICES:
            self.cb_source.addItem(label, value)
        quick.addWidget(self.cb_source)
        self.sp_qty = QSpinBox()
        self.sp_qty.setRange(1, 999)
        self.sp_qty.setValue(1)
        self.sp_qty.setPrefix("×")
        quick.addWidget(self.sp_qty)
        self.btn_sell = QPushButton("卖出")
        self.btn_restock = QPushButton("补货")
        self.btn_restock.setProperty("variant", "ghost")
        quick.addWidget(self.btn_sell)
        quick.addWidget(self.btn_restock)
        self.status = pill("就绪", "blue")
        self.status.setVisible(False)
        quick.addWidget(self.status)
        self.body.addLayout(quick)

        self.lbl_hint = hint_label(
            "提示：表单保存已有 SKU 时，库存会调整到填写的数值；表格行内按钮固定卖出/补货 1 件。"
        )
        self.body.addWidget(self.lbl_hint)

        # ---------------- 库存表 + 流水表 ----------------
        self.tabs = QTabWidget()
        self.tbl_inventory = QTableWidget()
        setup_table(
            self.tbl_inventory,
            ["SKU", "商品名", "品类", "进价", "售价", "当前库存", "更新时间", "操作"],
            {0: 85, 1: 150, 2: 80, 3: 80, 4: 80, 5: 90, 6: 145},
        )
        self.tabs.addTab(self.tbl_inventory, "当前库存")
        self.tbl_events = QTableWidget()
        setup_table(
            self.tbl_events,
            ["时间", "SKU", "商品名", "类型", "变动", "变动后库存", "来源", "订单号", "备注"],
            {0: 145, 1: 85, 2: 130, 3: 60, 4: 70, 5: 90, 6: 70, 7: 170},
        )
        self.tabs.addTab(self.tbl_events, "变动记录")
        self.body.addWidget(self.tabs, 1)

        self.sp_stock.valueChanged.connect(self._mark_stock_touched)
        self.btn_save.clicked.connect(self._save_product)
        self.btn_load.clicked.connect(self._load_selected)
        self.btn_clear.clicked.connect(self._clear_form)
        self.btn_sell.clicked.connect(self._sell_by_code)
        self.btn_restock.clicked.connect(self._restock_by_code)
        self.ed_code.returnPressed.connect(self._sell_by_code)
        self.tbl_inventory.itemSelectionChanged.connect(self._load_selected)

        self.refresh()

    # ==========================================================
    # 数据刷新
    # ==========================================================
    def refresh(self) -> None:
        try:
            self._all_inventory = realtime.inventory_rows()
            events = realtime.recent_events(200)
        except Exception as exc:
            style_pill(self.status, "读取失败", "red")
            self.status.setVisible(True)
            self.lbl_hint.setText(f"读取实时库存失败：{exc}")
            return

        self._fill_inventory(self._all_inventory)
        self._fill_events(events)
        self.tabs.setTabText(0, f"当前库存（{len(self._all_inventory)}）")
        self.tabs.setTabText(1, f"变动记录（{len(events)}）")

    def _fill_inventory(self, rows: list[dict]) -> None:
        # 先移除上一轮的行内按钮，避免刷新后旧控件残留在表格左侧
        for r in range(self.tbl_inventory.rowCount()):
            old = self.tbl_inventory.cellWidget(r, 7)
            if old is not None:
                old.hide()
                self.tbl_inventory.removeCellWidget(r, 7)
                old.setParent(None)
                old.deleteLater()
        table_rows = []
        for row in rows:
            table_rows.append(
                [
                    row["sku_id"],
                    row["sku_name"] or "—",
                    row["category"] or "—",
                    f"{row['cost']:.2f}",
                    f"{row['price']:.2f}",
                    f"{row['stock_qty']:g}",
                    row["snapshot_date"] or "—",
                    "",
                ]
            )
        fill_table(self.tbl_inventory, table_rows, numeric_columns={3, 4, 5})
        self.tbl_inventory.verticalHeader().setDefaultSectionSize(38)

        for index, row in enumerate(rows):
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(2, 1, 2, 1)
            layout.setSpacing(4)
            sell = QPushButton("卖出 1")
            sell.setProperty("variant", "danger")
            sell.setFixedHeight(30)
            sell.clicked.connect(
                lambda checked=False, sku=row["sku_id"]: self._quick_action(sku, "sale", 1)
            )
            restock = QPushButton("补货 1")
            restock.setProperty("variant", "ghost")
            restock.setFixedHeight(30)
            restock.clicked.connect(
                lambda checked=False, sku=row["sku_id"]: self._quick_action(sku, "restock", 1)
            )
            layout.addWidget(sell)
            layout.addWidget(restock)
            self.tbl_inventory.setCellWidget(index, 7, container)

    def _fill_events(self, events: list[dict]) -> None:
        rows = []
        colors = {}
        for index, event in enumerate(events):
            rows.append(
                [
                    event["ts"],
                    event["sku_id"],
                    event.get("sku_name") or "—",
                    realtime.ACTION_LABELS.get(event["action"], event["action"]),
                    f"{event['delta']:+g}",
                    f"{event['stock_after']:g}",
                    realtime.SOURCE_LABELS.get(event["source"], event["source"]),
                    event["order_id"] or "—",
                    event["note"] or "",
                ]
            )
            color = ACTION_COLORS.get(event["action"])
            if color:
                colors[index] = color
        fill_table(self.tbl_events, rows, numeric_columns={4, 5}, row_colors=colors)

    # ==========================================================
    # 表单
    # ==========================================================
    def _mark_stock_touched(self, *args) -> None:
        self._stock_touched = True

    def _selected_sku(self) -> str:
        selected = self.tbl_inventory.selectedItems()
        if not selected:
            return ""
        return self.tbl_inventory.item(selected[0].row(), 0).text()

    def _load_selected(self) -> None:
        sku = self._selected_sku()
        if not sku:
            return
        for row in self._all_inventory:
            if row["sku_id"] == sku:
                self.ed_sku.setText(row["sku_id"])
                self.ed_name.setText(row["sku_name"] or "")
                self.ed_category.setText(row["category"] or "")
                self.sp_cost.setValue(float(row["cost"]))
                self.sp_price.setValue(float(row["price"]))
                self.sp_stock.setValue(float(row["stock_qty"]))
                self._stock_touched = False
                break

    def _clear_form(self) -> None:
        self.ed_sku.clear()
        self.ed_name.clear()
        self.ed_category.clear()
        self.sp_cost.setValue(0)
        self.sp_price.setValue(0)
        self.sp_stock.setValue(0)
        self._stock_touched = False
        self.ed_sku.setFocus()

    def _save_product(self) -> None:
        sku = self.ed_sku.text().strip()
        existing = any(item["sku_id"] == sku for item in self._all_inventory)
        stock_value = self.sp_stock.value() if (not existing or self._stock_touched) else None
        try:
            row = realtime.save_product(
                sku_id=sku,
                sku_name=self.ed_name.text(),
                category=self.ed_category.text(),
                cost=self.sp_cost.value(),
                price=self.sp_price.value(),
                stock_qty=stock_value,
            )
        except realtime.RealtimeError as exc:
            style_pill(self.status, str(exc), "red")
            self.status.setVisible(True)
            return
        style_pill(
            self.status,
            f"已保存 {row['sku_id']} · 库存 {row['stock_qty']:g}",
            "green",
        )
        self.status.setVisible(True)
        self._stock_touched = False
        self.refresh()
        self.data_changed.emit("realtime")

    def _quick_action(self, sku: str, action: str, qty: int) -> None:
        try:
            if action == "sale":
                result = realtime.record_sale(sku, qty=qty)
                text = f"卖出 {result['sku_name'] or sku} · 库存 {result['stock_after']:g}"
            else:
                result = realtime.record_restock(sku, qty=qty)
                text = f"补货 {result['sku_name'] or sku} · 库存 {result['stock_after']:g}"
        except realtime.InsufficientStock as exc:
            style_pill(self.status, "库存不足", "red")
            self.status.setVisible(True)
            self.lbl_hint.setText(str(exc))
            return
        except realtime.RealtimeError as exc:
            style_pill(self.status, str(exc), "red")
            self.status.setVisible(True)
            return
        if self.ed_sku.text().strip() == sku:
            self.sp_stock.setValue(float(result["stock_after"]))
            self._stock_touched = False
        style_pill(self.status, text, "green")
        self.status.setVisible(True)
        self.refresh()
        self.data_changed.emit("realtime")

    # ==========================================================
    # 扫码 / 手输
    # ==========================================================
    def _sell_by_code(self) -> None:
        code = self.ed_code.text().strip()
        if not code:
            style_pill(self.status, "请输入 SKU / 商品名 / 条码", "amber")
            self.status.setVisible(True)
            return
        source = self.cb_source.currentData()
        try:
            result = realtime.record_sale_by_code(
                code, qty=self.sp_qty.value(), source=source
            )
        except realtime.InsufficientStock as exc:
            style_pill(self.status, "库存不足", "red")
            self.status.setVisible(True)
            self.lbl_hint.setText(str(exc))
            return
        except realtime.RealtimeError as exc:
            style_pill(self.status, str(exc), "red")
            self.status.setVisible(True)
            return
        style_pill(
            self.status,
            f"卖出 {result['sku_name'] or result['sku_id']} ×{result['qty']} · "
            f"库存 {result['stock_after']:g}",
            "green",
        )
        if self.ed_sku.text().strip() == result["sku_id"]:
            self.sp_stock.setValue(float(result["stock_after"]))
            self._stock_touched = False
        self.status.setVisible(True)
        self.ed_code.clear()
        self.refresh()
        self.data_changed.emit("realtime")

    def _restock_by_code(self) -> None:
        code = self.ed_code.text().strip()
        if not code:
            style_pill(self.status, "请输入 SKU / 商品名 / 条码", "amber")
            self.status.setVisible(True)
            return
        source = self.cb_source.currentData()
        sku = realtime.resolve_code(code, source=source)
        if not sku:
            style_pill(self.status, "没有找到对应商品", "red")
            self.status.setVisible(True)
            return
        try:
            result = realtime.record_restock(sku, qty=self.sp_qty.value(), source=source)
        except realtime.RealtimeError as exc:
            style_pill(self.status, str(exc), "red")
            self.status.setVisible(True)
            return
        style_pill(
            self.status,
            f"补货 {result['sku_name'] or sku} ×{result['qty']} · "
            f"库存 {result['stock_after']:g}",
            "green",
        )
        if self.ed_sku.text().strip() == result["sku_id"]:
            self.sp_stock.setValue(float(result["stock_after"]))
            self._stock_touched = False
        self.status.setVisible(True)
        self.ed_code.clear()
        self.refresh()
        self.data_changed.emit("realtime")

    # ==========================================================
    def on_data_changed(self, source: str = "") -> None:
        self.refresh()

    def on_show(self) -> None:
        self.refresh()
