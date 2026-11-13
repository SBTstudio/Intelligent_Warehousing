"""实时库存 / 收银辅助测试。"""

from __future__ import annotations

import pytest

from app.core import realtime
from app.db import schema


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "DB_PATH", tmp_path / "realtime.db")
    schema.init_db()
    realtime._CODE_RESOLVERS.clear()
    yield
    realtime._CODE_RESOLVERS.clear()


def test_create_product_and_sell(temp_db):
    row = realtime.save_product(
        "S001", "可乐", "饮料", cost=2.0, price=3.5, stock_qty=10,
        ts="2026-11-13 10:00:00",
    )
    assert row["stock_qty"] == 10.0

    events = realtime.recent_events()
    assert events[0]["action"] == realtime.ACTION_CREATE
    assert events[0]["delta"] == 10.0
    assert events[0]["ts"] == "2026-11-13 10:00:00"

    sale = realtime.record_sale("S001", qty=1, ts="2026-11-13 10:01:00")
    assert sale["stock_after"] == 9.0
    assert sale["order_id"].startswith("RT20261113100100")

    inv = {row["sku_id"]: row for row in realtime.inventory_rows()}
    assert inv["S001"]["stock_qty"] == 9.0
    assert inv["S001"]["snapshot_date"] == "2026-11-13 10:01:00"

    sales = schema.fetch_sales(since="2026-11-13")
    assert len(sales) == 1
    assert sales[0]["sku_id"] == "S001"
    assert sales[0]["qty"] == 1
    assert sales[0]["unit_price"] == pytest.approx(3.5)

    event = realtime.recent_events()[0]
    assert event["action"] == realtime.ACTION_SALE
    assert event["delta"] == -1.0
    assert event["stock_after"] == 9.0
    assert event["order_id"] == sale["order_id"]


def test_restock_and_insufficient_stock(temp_db):
    realtime.save_product("S002", "面包", "烘焙", cost=4.0, price=7.0, stock_qty=2)
    restock = realtime.record_restock("S002", qty=5, unit_cost=4.5)
    assert restock["stock_after"] == 7.0

    with pytest.raises(realtime.InsufficientStock):
        realtime.record_sale("S002", qty=100)

    # 库存不足时不能产生销售流水
    assert schema.fetch_sales() == []


def test_update_product_and_adjust_stock(temp_db):
    realtime.save_product("S003", "旧名称", "零食", cost=1.0, price=2.0, stock_qty=3)
    row = realtime.save_product(
        "S003", "新名称", "零食", cost=1.2, price=2.5, stock_qty=8
    )
    assert row["sku_name"] == "新名称"
    assert row["stock_qty"] == 8.0
    assert row["price"] == pytest.approx(2.5)
    events = realtime.recent_events()
    assert events[0]["action"] == realtime.ACTION_ADJUST
    assert events[0]["delta"] == 5.0


def test_missing_product_errors(temp_db):
    with pytest.raises(realtime.ProductNotFound):
        realtime.record_sale("NOPE")
    with pytest.raises(realtime.ProductNotFound):
        realtime.record_restock("NOPE")


def test_record_sale_by_code_and_resolver(temp_db):
    realtime.save_product("S004", "扫码商品", "测试", cost=1.0, price=1.5, stock_qty=5)

    # 默认可以按 SKU 或商品名精确匹配
    result = realtime.record_sale_by_code("扫码商品")
    assert result["sku_id"] == "S004"
    assert result["stock_after"] == 4.0

    # 注册条形码解析器后，可以按外部条码卖
    realtime.register_code_resolver(
        "barcode", lambda code: "S004" if code == "6900000000001" else None
    )
    result = realtime.record_sale_by_code("6900000000001", source="barcode")
    assert result["source"] == "barcode"
    assert result["stock_after"] == 3.0


def test_events_are_timestamped_and_ordered(temp_db):
    realtime.save_product("S005", "时间测试", "测试", 1, 2, 10)
    realtime.record_sale("S005", ts="2026-11-13 11:00:00")
    realtime.record_restock("S005", qty=2, ts="2026-11-13 12:00:00")
    events = realtime.recent_events()
    assert [e["action"] for e in events[:2]] == [
        realtime.ACTION_RESTOCK,
        realtime.ACTION_SALE,
    ]
    assert events[0]["ts"] == "2026-11-13 12:00:00"
    assert events[1]["ts"] == "2026-11-13 11:00:00"


def test_edit_metadata_without_changing_stock(temp_db):
    realtime.save_product("S006", "原名", "测试", 1, 2, 10)
    row = realtime.save_product("S006", "新名", "测试", 1.5, 3.0)
    assert row["stock_qty"] == 10.0
    assert row["price"] == pytest.approx(3.0)
    # 只改档案不应产生库存调整事件
    assert all(e["action"] != realtime.ACTION_ADJUST for e in realtime.recent_events())
