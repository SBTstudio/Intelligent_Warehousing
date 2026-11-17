"""首页 / 精简版使用指南。

首页提供营业入口（收银台、实时库存、数据导入）和一份可随时打开的精简指南。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core import realtime
from app.db import schema
from app.ui.base_page import WorkPage
from app.ui.helpers import hint_label
from app.ui.theme import COLORS

GUIDE_TEXT = """智能仓储管理系统 · 精简版使用指南

一、第一次使用
1. 双击「安装环境.bat」安装依赖，双击「run.bat」启动。
2. 没有数据时，到「数据导入」点「一键载入示例数据」。
3. 要导入自己的数据：在「数据导入」下载中文空白模板，填好后选择文件导入。

二、商品与库存
1. 打开「实时库存」。
2. 填写商品编号、名称、品类、进价、售价、库存，点「保存 / 更新商品」。
3. 表格里可以直接点「卖出 1」「补货 1」。
4. 每次变动都会记录时间戳；「变动记录」可以回看。

三、营业收银
1. 打开「收银台」。
2. 在顶部输入 SKU、商品名或条码，按回车加入当前小票。
3. 同一张小票可以连续加多种商品；同一 SKU 会合并数量。
4. 点「结账」，生成一个完整订单（一个订单号、多条商品明细）。
5. 库存不足时不会结账，也不会产生半张订单。

四、补货与报告
1. 「库存与补货」：查看安全库存、补货点、建议补货日和畅销/滞销。
2. 「分析报告」：生成经营周报、滞销归因、陈列建议、换季推荐。
3. 默认使用本地 Ollama；也可以在「参数配置」切换第三方 OpenAI 兼容 API。

五、数据安全
1. 数据保存在本机 SQLite；安装包版本在用户数据目录。
2. 「参数配置」可以备份数据库。
3. 第三方 API 只接收聚合摘要，不上传原始 CSV；默认本地模式不联网。

六、条码枪 / NFC
「收银台」和「实时库存」的输入框已经走统一接口；
后续接硬件时，在程序启动处注册解析器即可：

    from app.core import realtime
    realtime.register_code_resolver("barcode", resolve_barcode)

更完整的说明见 docs/用户手册.md。
"""


class GuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("精简版使用指南")
        self.resize(760, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)

        title = QLabel("精简版使用指南")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(GUIDE_TEXT)
        layout.addWidget(text, 1)

        close = QPushButton("知道了")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)


class HomePage(WorkPage):
    navigate = Signal(str)

    def __init__(self):
        super().__init__(
            "首页",
            "欢迎使用智能仓储管理系统。你可以直接从收银台开始营业，也可以先导入数据做分析。",
        )
        self.setWindowTitle("首页")

        hero = QWidget()
        hero.setObjectName("Hero")
        hero.setStyleSheet(
            "QWidget#Hero { background: #0F6E56; border-radius: 12px; }"
        )
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 20, 24, 20)
        hero_layout.setSpacing(4)
        hello = QLabel("今天也把库存管明白")
        hello.setStyleSheet("color: #FFFFFF; font-size: 24px; font-weight: 700;")
        sub = QLabel("收银、建档、补货、分析，都在一个软件里完成。")
        sub.setStyleSheet("color: #CFE9DF; font-size: 13px;")
        hero_layout.addWidget(hello)
        hero_layout.addWidget(sub)
        self.body.addWidget(hero)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.stat_products = self._stat_card("商品数", "0")
        self.stat_stock = self._stat_card("库存总量", "0")
        self.stat_orders = self._stat_card("累计订单", "0")
        self.stat_events = self._stat_card("库存变动", "0")
        for card in (self.stat_products, self.stat_stock, self.stat_orders, self.stat_events):
            stats.addWidget(card)
        self.body.addLayout(stats)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        btn_cashier = QPushButton("打开收银台")
        btn_realtime = QPushButton("实时库存")
        btn_realtime.setProperty("variant", "ghost")
        btn_import = QPushButton("导入数据")
        btn_import.setProperty("variant", "ghost")
        btn_guide = QPushButton("查看精简版使用指南")
        btn_guide.setProperty("variant", "ghost")
        actions.addWidget(btn_cashier)
        actions.addWidget(btn_realtime)
        actions.addWidget(btn_import)
        actions.addWidget(btn_guide)
        actions.addStretch(1)
        self.body.addLayout(actions)

        btn_cashier.clicked.connect(lambda: self.navigate.emit("cashier"))
        btn_realtime.clicked.connect(lambda: self.navigate.emit("realtime"))
        btn_import.clicked.connect(lambda: self.navigate.emit("import"))
        btn_guide.clicked.connect(self._show_guide)

        steps = QHBoxLayout()
        steps.setSpacing(10)
        steps.addWidget(
            self._step_card(
                "1  建档 / 导入",
                "在「实时库存」录入商品和库存，或在「数据导入」下载中文模板批量导入。",
            )
        )
        steps.addWidget(
            self._step_card(
                "2  营业收银",
                "在「收银台」连续扫码/手输商品，点「结账」生成一张完整小票。",
            )
        )
        steps.addWidget(
            self._step_card(
                "3  看补货 / 报告",
                "「库存与补货」看建议补货日，「分析报告」生成本地模型或第三方 API 报告。",
            )
        )
        self.body.addLayout(steps)

        self.lbl_tip = hint_label(
            "提示：入库、卖出、补货都会记录时间戳；库存不足会拒绝操作，不会产生半张订单。"
        )
        self.body.addWidget(self.lbl_tip)
        self.body.addStretch(1)

        self.refresh()

    # ==========================================================
    def _stat_card(self, title: str, value: str) -> QWidget:
        card = QWidget()
        card.setObjectName("StatCard")
        card.setStyleSheet(
            "QWidget#StatCard { background: #FFFFFF; border: 1px solid #E2DFD4;"
            " border-radius: 10px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        label = QLabel(title)
        label.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        number = QLabel(value)
        number.setStyleSheet(
            f"color: {COLORS['green']}; font-size: 22px; font-weight: 700;"
        )
        layout.addWidget(label)
        layout.addWidget(number)
        card.value_label = number  # type: ignore[attr-defined]
        return card

    def _step_card(self, title: str, body: str) -> QWidget:
        card = QWidget()
        card.setObjectName("StepCard")
        card.setStyleSheet(
            "QWidget#StepCard { background: #FFFFFF; border: 1px solid #E2DFD4;"
            " border-radius: 10px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setStyleSheet(
            f"color: {COLORS['green']}; font-size: 14px; font-weight: 700;"
        )
        text = QLabel(body)
        text.setWordWrap(True)
        text.setStyleSheet(f"color: {COLORS['ink']}; font-size: 12px;")
        layout.addWidget(heading)
        layout.addWidget(text)
        layout.addStretch(1)
        return card

    # ==========================================================
    def refresh(self) -> None:
        try:
            stats = schema.db_stats()
            products = realtime.inventory_rows()
            stock_total = sum(float(row["stock_qty"]) for row in products)
            self.stat_products.value_label.setText(f"{stats.get('products', 0):,}")
            self.stat_stock.value_label.setText(f"{stock_total:,.0f}")
            self.stat_orders.value_label.setText(f"{stats.get('transactions', 0):,}")
            self.stat_events.value_label.setText(
                f"{stats.get('inventory_events', 0):,}"
            )
        except Exception:
            pass

    def _show_guide(self) -> None:
        GuideDialog(self).exec()

    def on_show(self) -> None:
        self.refresh()
