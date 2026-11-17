"""收银台页。

和「实时库存」的区别：
    - 实时库存是单项操作：点一次卖一件；
    - 收银台把多次扫码/手输先放进购物车，最后点「结账」，
      生成一个 order_id、多条 transaction_items，作为一张完整小票。

以后接条码枪/NFC 时，输入框仍然走 `realtime.resolve_code()`，
只需要注册解析器即可。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
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


class CashierPage(WorkPage):
    sale_completed = Signal(str)

    def __init__(self):
        super().__init__(
            "收银台",
            "扫描或输入商品加入当前小票，可以连续加多件；点「结账」后才生成一张完整订单。"
            "适合营业时作为收银机的补充。",
        )
        self.setWindowTitle("收银台")
        self._products: list[dict] = []
        self._cart: list[dict] = []

        # ---------------- 扫码录入 ----------------
        scan_row = QHBoxLayout()
        scan_row.setSpacing(8)
        scan_row.addWidget(QLabel("扫码 / 手输"))
        self.ed_code = QLineEdit()
        self.ed_code.setPlaceholderText("输入 SKU、商品名或条形码，按回车加入小票")
        self.ed_code.returnPressed.connect(self._add_by_code)
        scan_row.addWidget(self.ed_code, 1)
        self.cb_source = QComboBox()
        for label, value in SOURCE_CHOICES:
            self.cb_source.addItem(label, value)
        scan_row.addWidget(self.cb_source)
        self.sp_qty = QSpinBox()
        self.sp_qty.setRange(1, 999)
        self.sp_qty.setValue(1)
        self.sp_qty.setPrefix("×")
        scan_row.addWidget(self.sp_qty)
        self.btn_add = QPushButton("加入小票")
        scan_row.addWidget(self.btn_add)
        self.status = pill("等待录入", "blue")
        self.status.setVisible(False)
        scan_row.addWidget(self.status)
        self.body.addLayout(scan_row)

        self.lbl_hint = hint_label(
            "提示：单击商品行选中后点「加入选中商品」，或直接双击/点行内「加入」；"
            "同一 SKU 会合并数量，结账前会校验库存。"
        )
        self.body.addWidget(self.lbl_hint)

        # ---------------- 左：商品列表；右：购物车 ----------------
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_top = QHBoxLayout()
        left_top.addWidget(QLabel("商品列表"))
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("搜索 SKU / 名称 / 品类")
        self.ed_search.textChanged.connect(self._render_products)
        left_top.addWidget(self.ed_search, 1)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setProperty("variant", "ghost")
        self.btn_refresh.clicked.connect(self.refresh)
        left_top.addWidget(self.btn_refresh)
        self.btn_add_selected = QPushButton("加入选中商品")
        self.btn_add_selected.setEnabled(False)
        self.btn_add_selected.clicked.connect(self._add_selected_product)
        left_top.addWidget(self.btn_add_selected)
        left_layout.addLayout(left_top)

        self.tbl_products = QTableWidget()
        setup_table(
            self.tbl_products,
            ["SKU", "商品名", "售价", "当前库存", "操作"],
            {0: 75, 1: 130, 2: 65, 3: 75, 4: 60},
        )
        self.tbl_products.doubleClicked.connect(self._add_selected_product)
        self.tbl_products.itemSelectionChanged.connect(self._update_selected_button)
        left_layout.addWidget(self.tbl_products, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_top = QHBoxLayout()
        right_top.addWidget(QLabel("当前小票"))
        right_top.addStretch(1)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setProperty("variant", "ghost")
        self.btn_clear.clicked.connect(self._clear_cart)
        right_top.addWidget(self.btn_clear)
        right_layout.addLayout(right_top)

        self.tbl_cart = QTableWidget()
        setup_table(
            self.tbl_cart,
            ["SKU", "商品名", "单价", "数量", "小计", "操作"],
            {0: 62, 1: 100, 2: 60, 3: 45, 4: 65, 5: 55},
        )
        right_layout.addWidget(self.tbl_cart, 1)

        total_row = QHBoxLayout()
        self.lbl_count = QLabel("0 件")
        self.lbl_count.setObjectName("Muted")
        total_row.addWidget(self.lbl_count)
        total_row.addStretch(1)
        self.lbl_total = QLabel("合计 ¥0.00")
        self.lbl_total.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #0F6E56;"
        )
        total_row.addWidget(self.lbl_total)
        right_layout.addLayout(total_row)

        self.btn_checkout = QPushButton("结账")
        self.btn_checkout.setMinimumHeight(40)
        right_layout.addWidget(self.btn_checkout)
        splitter.addWidget(right)

        splitter.setSizes([600, 450])
        self.body.addWidget(splitter, 1)

        self.btn_add.clicked.connect(self._add_by_code)
        self.btn_checkout.clicked.connect(self._checkout)
        self.refresh()

    # ==========================================================
    def refresh(self) -> None:
        try:
            self._products = realtime.inventory_rows()
        except Exception as exc:
            style_pill(self.status, "读取商品失败", "red")
            self.status.setVisible(True)
            self.lbl_hint.setText(f"读取商品失败：{exc}")
            return
        self._render_products()
        self._render_cart()

    def _render_products(self) -> None:
        for r in range(self.tbl_products.rowCount()):
            old = self.tbl_products.cellWidget(r, 4)
            if old is not None:
                old.hide()
                self.tbl_products.removeCellWidget(r, 4)
                old.setParent(None)
                old.deleteLater()

        keyword = self.ed_search.text().strip().lower()
        rows = []
        visible_products = []
        for product in self._products:
            haystack = " ".join(
                [
                    str(product.get("sku_id", "")),
                    str(product.get("sku_name", "")),
                    str(product.get("category", "")),
                ]
            ).lower()
            if keyword and keyword not in haystack:
                continue
            visible_products.append(product)
            rows.append(
                [
                    product["sku_id"],
                    product["sku_name"] or "—",
                    f"¥{float(product['price']):.2f}",
                    f"{float(product['stock_qty']):g}",
                    "",
                ]
            )
        fill_table(self.tbl_products, rows, numeric_columns={2, 3})
        self.tbl_products.verticalHeader().setDefaultSectionSize(36)
        for index, product in enumerate(visible_products):
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(2, 1, 2, 1)
            add = QPushButton("加入")
            add.setFixedHeight(28)
            add.clicked.connect(
                lambda checked=False, sku=product["sku_id"]: self._add_sku(
                    sku, self.sp_qty.value()
                )
            )
            layout.addWidget(add)
            self.tbl_products.setCellWidget(index, 4, container)
        self._update_selected_button()

    def _render_cart(self) -> None:
        for r in range(self.tbl_cart.rowCount()):
            old = self.tbl_cart.cellWidget(r, 5)
            if old is not None:
                old.hide()
                self.tbl_cart.removeCellWidget(r, 5)
                old.setParent(None)
                old.deleteLater()

        rows = []
        total = 0.0
        count = 0
        for line in self._cart:
            subtotal = line["unit_price"] * line["qty"]
            total += subtotal
            count += line["qty"]
            rows.append(
                [
                    line["sku_id"],
                    line["sku_name"] or "—",
                    f"¥{line['unit_price']:.2f}",
                    str(line["qty"]),
                    f"¥{subtotal:.2f}",
                    "",
                ]
            )
        fill_table(self.tbl_cart, rows, numeric_columns={2, 3, 4})
        self.tbl_cart.verticalHeader().setDefaultSectionSize(36)

        for index, line in enumerate(self._cart):
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(2, 1, 2, 1)
            remove = QPushButton("移除")
            remove.setProperty("variant", "danger")
            remove.setFixedHeight(28)
            remove.clicked.connect(
                lambda checked=False, sku=line["sku_id"]: self._remove_line(sku)
            )
            layout.addWidget(remove)
            self.tbl_cart.setCellWidget(index, 5, container)

        self.lbl_count.setText(f"{count} 件 / {len(self._cart)} 行")
        self.lbl_total.setText(f"合计 ¥{total:.2f}")

    # ==========================================================
    def _product(self, sku: str) -> dict | None:
        for product in self._products:
            if product["sku_id"] == sku:
                return product
        return None

    def _cart_qty(self, sku: str) -> int:
        return sum(line["qty"] for line in self._cart if line["sku_id"] == sku)

    def _add_sku(self, sku: str, qty: int) -> None:
        product = self._product(sku)
        if product is None:
            style_pill(self.status, "商品不存在", "red")
            self.status.setVisible(True)
            return
        stock = float(product["stock_qty"])
        already = self._cart_qty(sku)
        if already + qty > stock:
            style_pill(
                self.status,
                f"{product['sku_name'] or sku} 库存只有 {stock:g}",
                "amber",
            )
            self.status.setVisible(True)
            return
        for line in self._cart:
            if line["sku_id"] == sku:
                line["qty"] += qty
                break
        else:
            self._cart.append(
                {
                    "sku_id": sku,
                    "sku_name": product["sku_name"],
                    "unit_price": float(product["price"]),
                    "qty": qty,
                }
            )
        style_pill(
            self.status,
            f"已加入 {product['sku_name'] or sku} ×{qty}",
            "green",
        )
        self.status.setVisible(True)
        self._render_cart()

    def _add_by_code(self) -> None:
        code = self.ed_code.text().strip()
        if not code:
            style_pill(self.status, "请输入 SKU / 商品名 / 条码", "amber")
            self.status.setVisible(True)
            return
        source = self.cb_source.currentData()
        sku = realtime.resolve_code(code, source=source)
        if not sku:
            style_pill(self.status, f"没有找到商品：{code}", "red")
            self.status.setVisible(True)
            return
        self._add_sku(sku, self.sp_qty.value())
        self.ed_code.clear()
        self.ed_code.setFocus()

    def _update_selected_button(self) -> None:
        enabled = bool(self.tbl_products.selectedItems())
        self.btn_add_selected.setEnabled(enabled)

    def _add_selected_product(self, *args) -> None:
        row = self.tbl_products.currentRow()
        if row < 0:
            return
        item = self.tbl_products.item(row, 0)
        if item is not None:
            self._add_sku(item.text(), self.sp_qty.value())

    def _remove_line(self, sku: str) -> None:
        self._cart = [line for line in self._cart if line["sku_id"] != sku]
        self._render_cart()

    def _clear_cart(self) -> None:
        self._cart.clear()
        self._render_cart()
        style_pill(self.status, "已清空小票", "blue")
        self.status.setVisible(True)

    # ==========================================================
    def _checkout(self) -> None:
        if not self._cart:
            style_pill(self.status, "小票为空，先加入商品", "amber")
            self.status.setVisible(True)
            return
        try:
            result = realtime.checkout_cart(
                [
                    {
                        "sku_id": line["sku_id"],
                        "qty": line["qty"],
                        "unit_price": line["unit_price"],
                    }
                    for line in self._cart
                ],
                source=self.cb_source.currentData(),
            )
        except realtime.InsufficientStock as exc:
            style_pill(self.status, "库存不足，未结账", "red")
            self.status.setVisible(True)
            self.lbl_hint.setText(str(exc))
            return
        except realtime.RealtimeError as exc:
            style_pill(self.status, str(exc), "red")
            self.status.setVisible(True)
            return

        self._cart.clear()
        self.refresh()
        style_pill(
            self.status,
            f"结账成功 · {result['order_id']} · ¥{result['total']:.2f}",
            "green",
        )
        self.status.setVisible(True)
        self.lbl_hint.setText(
            f"订单 {result['order_id']} 已写入，共 {len(result['items'])} 种商品，"
            f"时间 {result['ts']}"
        )
        self.sale_completed.emit(result["order_id"])

    # ==========================================================
    def on_data_changed(self, source: str = "") -> None:
        self.refresh()

    def on_show(self) -> None:
        self.refresh()
