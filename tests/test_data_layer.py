"""数据层测试 —— 这些测试现在应该全部通过。

运行：
    .venv/Scripts/python.exe -m pytest tests/ -v
"""

import csv
from pathlib import Path

from app.db import schema

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


def test_sample_files_exist():
    for name in ("receipts.csv", "products.csv", "inventory.csv", "receipts_dirty.csv"):
        assert (SAMPLE / name).exists(), f"缺少示例数据 {name}，请先运行 tools/make_fake_data.py"


def test_receipts_has_expected_columns():
    with (SAMPLE / "receipts.csv").open(encoding="utf-8-sig") as f:
        header = next(csv.reader(f))
    assert header == ["order_id", "sku_id", "qty", "date", "unit_price"]


def test_receipts_volume_is_reasonable():
    with (SAMPLE / "receipts.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    # 120 天、每天十来张小票，几千行是合理的
    assert 2000 < len(rows) < 12000


def test_all_skus_in_receipts_have_profile():
    with (SAMPLE / "products.csv").open(encoding="utf-8-sig") as f:
        known = {r["sku_id"] for r in csv.DictReader(f)}
    with (SAMPLE / "receipts.csv").open(encoding="utf-8-sig") as f:
        used = {r["sku_id"] for r in csv.DictReader(f)}
    assert used <= known, f"小票里出现了没有档案的 SKU：{used - known}"


def test_dirty_file_contains_invalid_rows():
    """故意造错的文件必须真的有问题，否则测不出校验逻辑。"""
    with (SAMPLE / "receipts_dirty.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    bad = 0
    for r in rows:
        if not r["sku_id"]:
            bad += 1
        elif int(float(r["qty"])) < 0:
            bad += 1
        elif "昨天" in r["date"]:
            bad += 1
        elif "." in r["qty"]:
            bad += 1
    assert bad >= 4, f"脏数据文件里只找到 {bad} 处问题，应该有 4 处以上"


def test_database_roundtrip():
    """建表 → 写入 → 读出，走一遍完整链路。"""
    schema.init_db()
    _cleanup_test_rows()

    n = schema.insert_products(
        [{"sku_id": "TEST01", "sku_name": "测试商品", "category": "测试", "cost": 1.0, "price": 2.0}]
    )
    assert n == 1

    n = schema.insert_sales(
        [{"order_id": "TEST_ORDER", "ts": "2026-01-01 10:00", "sku_id": "TEST01",
          "qty": 3, "unit_price": 2.0}]
    )
    assert n == 1

    schema.insert_inventory([{"sku_id": "TEST01", "stock_qty": 20}])

    rows = schema.fetch_sales(since="2026-01-01")
    mine = [r for r in rows if r["sku_id"] == "TEST01"]
    assert len(mine) == 1
    assert mine[0]["qty"] == 3

    inv = {r["sku_id"]: r for r in schema.fetch_inventory()}
    assert inv["TEST01"]["stock_qty"] == 20

    _cleanup_test_rows()


def test_reimport_is_idempotent():
    """同一个订单重复导入，明细不应该翻倍（三年数据下这是致命问题）。"""
    schema.init_db()
    row = [{"order_id": "DUP_ORDER", "ts": "2026-02-01 10:00", "sku_id": "TEST01",
            "qty": 2, "unit_price": 2.0}]

    _cleanup_test_rows()
    schema.insert_products(
        [{"sku_id": "TEST01", "sku_name": "测试商品", "category": "测试", "cost": 1.0, "price": 2.0}]
    )
    for _ in range(3):
        schema.insert_sales(row)

    mine = [r for r in schema.fetch_sales(since="2026-02-01") if r["order_id"] == "DUP_ORDER"]
    assert len(mine) == 1, f"重复导入产生了 {len(mine)} 条明细"
    _cleanup_test_rows()


def _cleanup_test_rows():
    """清掉本测试文件写进去的临时数据，保证测试可重复运行。"""
    with schema.get_conn() as conn:
        conn.execute("DELETE FROM transaction_items WHERE sku_id='TEST01'")
        conn.execute("DELETE FROM transactions WHERE order_id IN ('TEST_ORDER','DUP_ORDER')")
        conn.execute("DELETE FROM products WHERE sku_id='TEST01'")
        conn.execute("DELETE FROM inventory WHERE sku_id='TEST01'")


def test_config_defaults_and_write():
    schema.init_db()
    cfg = schema.get_config()
    assert "service_level" in cfg and "min_support" in cfg

    schema.set_config("min_support", "0.025")
    assert schema.get_config()["min_support"] == "0.025"
    schema.set_config("min_support", "0.010")  # 改回去，不影响其他测试
