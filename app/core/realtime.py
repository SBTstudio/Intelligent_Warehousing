"""实时库存 / 收银辅助。

这个模块让软件不只做"事后分析"，而是营业过程中也能用：

    · 新增 / 编辑商品档案（名称、进价、售价、当前库存）
    · 卖出一件：库存 -1，同时写一条销售流水和时间戳
    · 补货：库存 +N，写一条补货流水和时间戳
    · 每次变动都写 inventory_events，可按时间回看

扫码 / NFC 扩展点
-----------------
`register_code_resolver(source, resolver)` 允许以后接入条码枪或 NFC 读卡器：

    def resolve_barcode(code: str) -> str | None:
        return barcode_map.get(code)

    register_code_resolver("barcode", resolve_barcode)
    record_sale_by_code("6901234567890", source="barcode")

默认的 resolver 会把 code 当成 SKU 或商品名称做精确匹配。
UI 里的"扫码/NFC 录入"输入框已经走这条统一接口，后续只需要注册解析器。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.db import schema

SOURCE_MANUAL = "manual"
SOURCE_BARCODE = "barcode"
SOURCE_NFC = "nfc"
SOURCE_LABELS = {
    SOURCE_MANUAL: "手动",
    SOURCE_BARCODE: "条形码",
    SOURCE_NFC: "NFC",
}

ACTION_SALE = "sale"
ACTION_RESTOCK = "restock"
ACTION_CREATE = "create"
ACTION_ADJUST = "adjust"
ACTION_LABELS = {
    ACTION_SALE: "卖出",
    ACTION_RESTOCK: "补货",
    ACTION_CREATE: "建档",
    ACTION_ADJUST: "调整",
}


class RealtimeError(RuntimeError):
    """实时库存操作失败。"""


class ProductNotFound(RealtimeError):
    """SKU 不存在。"""


class InsufficientStock(RealtimeError):
    """库存不足。"""


@dataclass
class StockEvent:
    id: int
    sku_id: str
    ts: str
    action: str
    delta: float
    stock_after: float
    unit_price: float
    cost: float
    source: str
    order_id: str
    note: str


def _now(ts: str | datetime | date | None = None) -> str:
    if ts is None:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(ts, date):
        return f"{ts.isoformat()} 00:00:00"
    text = str(ts).strip()
    if len(text) == 10:
        return f"{text} 00:00:00"
    return text


def _source(value: str | None) -> str:
    source = str(value or SOURCE_MANUAL).strip().lower()
    return source if source in SOURCE_LABELS else SOURCE_MANUAL


def _product(conn, sku_id: str):
    return conn.execute(
        "SELECT sku_id, sku_name, category, cost, price, updated_at "
        "FROM products WHERE sku_id = ?",
        (sku_id,),
    ).fetchone()


def _latest_stock(conn, sku_id: str) -> float | None:
    row = conn.execute(
        "SELECT stock_qty FROM inventory WHERE sku_id = ? "
        "ORDER BY snapshot_date DESC LIMIT 1",
        (sku_id,),
    ).fetchone()
    return None if row is None else float(row["stock_qty"])


def _write_stock(conn, sku_id: str, stock: float, ts: str, cost: float) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO inventory (sku_id, snapshot_date, stock_qty, cost) "
        "VALUES (?, ?, ?, ?)",
        (sku_id, ts, float(max(0.0, stock)), float(max(0.0, cost))),
    )
    conn.execute(
        "UPDATE products SET updated_at = ? WHERE sku_id = ?",
        (ts, sku_id),
    )


def _log_event(
    conn,
    *,
    sku_id: str,
    ts: str,
    action: str,
    delta: float,
    stock_after: float,
    unit_price: float = 0.0,
    cost: float = 0.0,
    source: str = SOURCE_MANUAL,
    order_id: str = "",
    note: str = "",
) -> int:
    cursor = conn.execute(
        "INSERT INTO inventory_events "
        "(sku_id, ts, action, delta, stock_after, unit_price, cost, source, order_id, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sku_id,
            ts,
            action,
            float(delta),
            float(stock_after),
            float(unit_price),
            float(cost),
            source,
            order_id,
            note,
        ),
    )
    return int(cursor.lastrowid)


def _new_order_id(conn, ts: str) -> str:
    base = "".join(ch for ch in ts if ch.isdigit())[:14] or "00000000000000"
    for _ in range(20):
        candidate = f"RT{base}{uuid.uuid4().hex[:4].upper()}"
        exists = conn.execute(
            "SELECT 1 FROM transactions WHERE order_id = ?", (candidate,)
        ).fetchone()
        if not exists:
            return candidate
    raise RealtimeError("无法生成唯一订单号，请稍后重试")


def _stock_row(conn, sku_id: str) -> dict[str, Any]:
    product = _product(conn, sku_id)
    if product is None:
        raise ProductNotFound(f"商品 {sku_id} 不存在")
    stock = _latest_stock(conn, sku_id)
    return {
        "sku_id": product["sku_id"],
        "sku_name": product["sku_name"],
        "category": product["category"],
        "cost": float(product["cost"]),
        "price": float(product["price"]),
        "stock_qty": 0.0 if stock is None else float(stock),
        "updated_at": product["updated_at"],
    }


# =====================================================================
# 商品建档 / 编辑
# =====================================================================
def save_product(
    sku_id: str,
    sku_name: str,
    category: str = "",
    cost: float = 0.0,
    price: float = 0.0,
    stock_qty: float | None = None,
    source: str = SOURCE_MANUAL,
    ts: str | datetime | date | None = None,
) -> dict[str, Any]:
    """新增或更新商品档案。

    新商品：写入 products、inventory，并记一条 action=create 的流水。
    已有商品：更新名称/品类/进价/售价；如果传了 stock_qty，则把库存调整到该值，
    并记一条 action=adjust 的流水。
    """
    sku = str(sku_id or "").strip()
    name = str(sku_name or "").strip()
    if not sku:
        raise RealtimeError("商品编号不能为空")
    if not name:
        raise RealtimeError("商品名称不能为空")
    try:
        cost_value = float(cost)
        price_value = float(price)
        target_stock = None if stock_qty is None else float(stock_qty)
    except (TypeError, ValueError) as exc:
        raise RealtimeError("进价、售价、库存必须是数字") from exc
    if cost_value < 0 or price_value < 0:
        raise RealtimeError("进价和售价不能为负数")
    if target_stock is not None and target_stock < 0:
        raise RealtimeError("库存不能为负数")

    ts_text = _now(ts)
    source_value = _source(source)
    category_value = str(category or "").strip()

    with schema.get_conn() as conn:
        existing = _product(conn, sku)
        if existing is None:
            conn.execute(
                "INSERT INTO products "
                "(sku_id, sku_name, category, cost, price, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sku, name, category_value, cost_value, price_value, ts_text),
            )
            initial = 0.0 if target_stock is None else target_stock
            _write_stock(conn, sku, initial, ts_text, cost_value)
            _log_event(
                conn,
                sku_id=sku,
                ts=ts_text,
                action=ACTION_CREATE,
                delta=initial,
                stock_after=initial,
                unit_price=price_value,
                cost=cost_value,
                source=source_value,
                note="新增商品档案",
            )
        else:
            conn.execute(
                "UPDATE products SET sku_name = ?, category = ?, cost = ?, price = ?, "
                "updated_at = ? WHERE sku_id = ?",
                (name, category_value, cost_value, price_value, ts_text, sku),
            )
            if target_stock is not None:
                current = _latest_stock(conn, sku)
                current_value = 0.0 if current is None else current
                delta = target_stock - current_value
                _write_stock(conn, sku, target_stock, ts_text, cost_value)
                if abs(delta) > 1e-9:
                    _log_event(
                        conn,
                        sku_id=sku,
                        ts=ts_text,
                        action=ACTION_ADJUST,
                        delta=delta,
                        stock_after=target_stock,
                        unit_price=price_value,
                        cost=cost_value,
                        source=source_value,
                        note="编辑商品时调整库存",
                    )
            elif _latest_stock(conn, sku) is None:
                _write_stock(conn, sku, 0.0, ts_text, cost_value)

        row = _stock_row(conn, sku)
    return row


# =====================================================================
# 卖出 / 补货
# =====================================================================
def record_sale(
    sku_id: str,
    qty: int = 1,
    unit_price: float | None = None,
    source: str = SOURCE_MANUAL,
    order_id: str | None = None,
    ts: str | datetime | date | None = None,
    note: str = "",
) -> dict[str, Any]:
    """卖出一件（或 qty 件）：扣库存、写销售流水、写库存事件。"""
    sku = str(sku_id or "").strip()
    try:
        quantity = int(qty)
    except (TypeError, ValueError) as exc:
        raise RealtimeError("卖出数量必须是整数") from exc
    if quantity <= 0:
        raise RealtimeError("卖出数量必须大于 0")

    ts_text = _now(ts)
    source_value = _source(source)
    with schema.get_conn() as conn:
        product = _product(conn, sku)
        if product is None:
            raise ProductNotFound(f"商品 {sku} 不存在")
        current = _latest_stock(conn, sku)
        current_value = 0.0 if current is None else current
        if current_value + 1e-9 < quantity:
            raise InsufficientStock(
                f"{product['sku_name'] or sku} 库存不足：当前 {current_value:g}，"
                f"需要卖出 {quantity}"
            )

        price = float(product["price"] if unit_price is None else unit_price)
        if price < 0:
            raise RealtimeError("成交单价不能为负数")
        order = str(order_id or "").strip() or _new_order_id(conn, ts_text)
        new_stock = current_value - quantity
        total = price * quantity

        conn.execute(
            "INSERT OR IGNORE INTO transactions (order_id, ts, total_amount) "
            "VALUES (?, ?, 0)",
            (order, ts_text),
        )
        conn.execute(
            "UPDATE transactions SET ts = ?, total_amount = total_amount + ? "
            "WHERE order_id = ?",
            (ts_text, total, order),
        )
        previous = conn.execute(
            "SELECT qty FROM transaction_items WHERE order_id = ? AND sku_id = ?",
            (order, sku),
        ).fetchone()
        previous_qty = 0 if previous is None else int(previous["qty"])
        conn.execute(
            "INSERT OR REPLACE INTO transaction_items "
            "(order_id, sku_id, qty, unit_price) VALUES (?, ?, ?, ?)",
            (order, sku, previous_qty + quantity, price),
        )

        _write_stock(conn, sku, new_stock, ts_text, float(product["cost"]))
        event_id = _log_event(
            conn,
            sku_id=sku,
            ts=ts_text,
            action=ACTION_SALE,
            delta=-quantity,
            stock_after=new_stock,
            unit_price=price,
            cost=float(product["cost"]),
            source=source_value,
            order_id=order,
            note=note,
        )
    return {
        "event_id": event_id,
        "sku_id": sku,
        "sku_name": product["sku_name"],
        "qty": quantity,
        "unit_price": price,
        "stock_after": new_stock,
        "order_id": order,
        "ts": ts_text,
        "source": source_value,
    }


def record_restock(
    sku_id: str,
    qty: int = 1,
    unit_cost: float | None = None,
    source: str = SOURCE_MANUAL,
    ts: str | datetime | date | None = None,
    note: str = "",
) -> dict[str, Any]:
    """补货：增加库存，可选更新进货成本，写库存事件。"""
    sku = str(sku_id or "").strip()
    try:
        quantity = int(qty)
    except (TypeError, ValueError) as exc:
        raise RealtimeError("补货数量必须是整数") from exc
    if quantity <= 0:
        raise RealtimeError("补货数量必须大于 0")

    ts_text = _now(ts)
    source_value = _source(source)
    with schema.get_conn() as conn:
        product = _product(conn, sku)
        if product is None:
            raise ProductNotFound(f"商品 {sku} 不存在")
        current = _latest_stock(conn, sku)
        current_value = 0.0 if current is None else current
        new_stock = current_value + quantity
        cost = float(product["cost"] if unit_cost is None else unit_cost)
        if cost < 0:
            raise RealtimeError("进货成本不能为负数")

        conn.execute(
            "UPDATE products SET cost = ?, updated_at = ? WHERE sku_id = ?",
            (cost, ts_text, sku),
        )
        _write_stock(conn, sku, new_stock, ts_text, cost)
        event_id = _log_event(
            conn,
            sku_id=sku,
            ts=ts_text,
            action=ACTION_RESTOCK,
            delta=quantity,
            stock_after=new_stock,
            unit_price=float(product["price"]),
            cost=cost,
            source=source_value,
            note=note,
        )
    return {
        "event_id": event_id,
        "sku_id": sku,
        "sku_name": product["sku_name"],
        "qty": quantity,
        "stock_after": new_stock,
        "ts": ts_text,
        "source": source_value,
    }


# =====================================================================
# 扫码 / NFC 扩展点
# =====================================================================
_CODE_RESOLVERS: dict[str, Callable[[str], str | None]] = {}


def register_code_resolver(source: str, resolver: Callable[[str], str | None]) -> None:
    """注册外部码解析器（条形码 / NFC）。

    resolver 接收原始码，返回 SKU 编号或 None。
    典型接入：条码枪的键盘输入、NFC 读卡器回调、外部中间件 HTTP 接口。
    """
    _CODE_RESOLVERS[_source(source)] = resolver


def resolve_code(code: str, source: str = SOURCE_MANUAL) -> str | None:
    """把扫码/NFC/手动输入解析成 SKU；默认按 SKU 或商品名精确匹配。"""
    text = str(code or "").strip()
    if not text:
        return None
    resolver = _CODE_RESOLVERS.get(_source(source))
    if resolver is not None:
        try:
            resolved = resolver(text)
        except Exception:
            resolved = None
        if resolved:
            return str(resolved)
    with schema.get_conn() as conn:
        row = conn.execute(
            "SELECT sku_id FROM products WHERE sku_id = ? OR sku_name = ? LIMIT 1",
            (text, text),
        ).fetchone()
    return None if row is None else str(row["sku_id"])


def record_sale_by_code(
    code: str,
    qty: int = 1,
    source: str = SOURCE_MANUAL,
    unit_price: float | None = None,
) -> dict[str, Any]:
    """扫码/NFC/手输后直接卖出；解析不到商品时抛 ProductNotFound。"""
    sku = resolve_code(code, source=source)
    if not sku:
        raise ProductNotFound(f"没有找到条码/编号对应的商品：{code}")
    return record_sale(sku, qty=qty, source=source, unit_price=unit_price)


# =====================================================================
# 查询
# =====================================================================
def inventory_rows() -> list[dict[str, Any]]:
    """当前库存列表（每个 SKU 的最新快照）。"""
    sql = (
        "SELECT p.sku_id, p.sku_name, p.category, p.cost, p.price, p.updated_at, "
        "       COALESCE(i.stock_qty, 0) AS stock_qty, "
        "       COALESCE(i.snapshot_date, p.updated_at) AS snapshot_date "
        "FROM products p "
        "LEFT JOIN inventory i ON i.sku_id = p.sku_id AND i.snapshot_date = ("
        "    SELECT MAX(snapshot_date) FROM inventory WHERE sku_id = p.sku_id"
        ") "
        "ORDER BY p.sku_id"
    )
    with schema.get_conn() as conn:
        return [dict(row) for row in conn.execute(sql)]


def recent_events(limit: int = 100) -> list[dict[str, Any]]:
    """最近的库存变动流水，最新的在前。"""
    with schema.get_conn() as conn:
        rows = conn.execute(
            "SELECT e.id, e.sku_id, COALESCE(p.sku_name, '') AS sku_name, "
            "       e.ts, e.action, e.delta, e.stock_after, e.unit_price, e.cost, "
            "       e.source, e.order_id, e.note "
            "FROM inventory_events e LEFT JOIN products p ON p.sku_id = e.sku_id "
            "ORDER BY e.id DESC LIMIT ?",
            (max(1, int(limit)),),
        )
        return [dict(row) for row in rows]


def stock_history(sku_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """某个 SKU（或全部）的库存变动历史。"""
    with schema.get_conn() as conn:
        if sku_id:
            rows = conn.execute(
                "SELECT e.*, COALESCE(p.sku_name, '') AS sku_name "
                "FROM inventory_events e LEFT JOIN products p ON p.sku_id = e.sku_id "
                "WHERE e.sku_id = ? ORDER BY e.id DESC LIMIT ?",
                (str(sku_id), max(1, int(limit))),
            )
        else:
            rows = conn.execute(
                "SELECT e.*, COALESCE(p.sku_name, '') AS sku_name "
                "FROM inventory_events e LEFT JOIN products p ON p.sku_id = e.sku_id "
                "ORDER BY e.id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
        return [dict(row) for row in rows]
