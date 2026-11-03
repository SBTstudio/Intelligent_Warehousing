"""数据导入与校验测试（M1）。

覆盖：编码识别、列名同义词、正常文件、GBK 文件、缺列、负数、非整数、
非法日期、库存数量、原始文件不被修改。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core import ingest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


def _write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_text(text, encoding=encoding)
    return path


def test_sniff_encoding_utf8_bom_and_gbk(tmp_path):
    utf8 = _write(tmp_path / "utf8.csv", "sku_id,qty,date\nS1,1,2026-01-01\n")
    assert ingest.sniff_encoding(utf8) in ("utf-8", "utf-8-sig")

    gbk = tmp_path / "gbk.csv"
    gbk.write_bytes("sku_id,商品名称,qty,date\nS1,可乐,1,2026-01-01\n".encode("gbk"))
    assert ingest.sniff_encoding(gbk) == "gbk"

    with pytest.raises(ValueError):
        bad = tmp_path / "bad.csv"
        bad.write_bytes(b"\xff\xfe\x00\x00\x00")
        ingest.sniff_encoding(bad)


def test_normalize_columns_aliases():
    mapping = ingest.normalize_columns(
        ["SKU", "商品名称", "购买数量（件）", "交易时间", "单价", "现有库存", "进货成本"]
    )
    assert mapping["SKU"] == "sku_id"
    assert mapping["商品名称"] == "sku_name"
    assert mapping["购买数量（件）"] == "qty"
    assert mapping["交易时间"] == "date"
    assert mapping["单价"] == "unit_price"
    assert mapping["现有库存"] == "stock_qty"
    assert mapping["进货成本"] == "cost"


def test_validate_sample_receipt_ok():
    result = ingest.validate_receipt(SAMPLE / "receipts.csv")
    assert result.ok, result.errors[:5]
    assert len(result.rows) == 4295
    first = result.rows[0]
    assert first["order_id"] == "T00001"
    assert first["sku_id"] == "S002"
    assert first["qty"] == 2
    assert first["date"].startswith("2026-06-16")
    assert first["unit_price"] == pytest.approx(4.0)


def test_validate_dirty_file_reports_line_numbers():
    result = ingest.validate_receipt(SAMPLE / "receipts_dirty.csv")
    assert result.ok is False
    assert len(result.errors) >= 4
    assert all(message.startswith("第 ") for message in result.errors)
    joined = "\n".join(result.errors)
    assert "sku_id 为空" in joined
    assert "必须是非负整数" in joined
    assert "无法解析为日期" in joined


def test_validate_receipt_missing_column(tmp_path):
    path = _write(tmp_path / "missing.csv", "sku_id,qty\nS1,1\n")
    result = ingest.validate_receipt(path)
    assert result.ok is False
    assert any("date" in message for message in result.errors)


def test_validate_receipt_bad_values(tmp_path):
    path = _write(
        tmp_path / "bad.csv",
        "order_id,sku_id,qty,date,unit_price\n"
        "T1,S1,-2,2026-01-01,1.0\n"
        "T2,S2,1.5,2026-01-01,1.0\n"
        "T3,S3,1,昨天下午,1.0\n",
    )
    result = ingest.validate_receipt(path)
    assert result.ok is False
    line_errors = [message for message in result.errors if message.startswith("第 ")]
    assert len(line_errors) == 3
    assert result.rows == []


def test_validate_receipt_gbk(tmp_path):
    path = tmp_path / "gbk.csv"
    path.write_bytes(
        "订单号,商品编号,数量,交易时间,单价\nT1,S1,2,2026-01-01 10:00,3.50\n".encode("gbk")
    )
    result = ingest.validate_receipt(path)
    assert result.ok, result.errors
    assert result.rows[0]["sku_id"] == "S1"
    assert result.rows[0]["qty"] == 2
    assert result.rows[0]["unit_price"] == pytest.approx(3.5)


def test_validate_inventory(tmp_path):
    good = _write(
        tmp_path / "inv.csv",
        "sku_id,sku_name,stock_qty,cost\nS1,可乐,20,2.0\n",
    )
    result = ingest.validate_inventory(good)
    assert result.ok
    assert result.rows[0]["stock_qty"] == pytest.approx(20.0)

    bad = _write(tmp_path / "inv_bad.csv", "sku_id,stock_qty\nS1,-1\n")
    result = ingest.validate_inventory(bad)
    assert result.ok is False
    assert "必须 ≥ 0" in result.errors[0]


def test_validate_products():
    result = ingest.validate_products(SAMPLE / "products.csv")
    assert result.ok
    assert len(result.rows) == 30
    assert result.rows[0]["sku_id"] == "S001"
    assert result.rows[0]["sku_name"] == "青岛啤酒"


def test_original_file_is_not_modified():
    """需求 2.2.1：导入校验绝不能修改用户原始文件。"""
    path = SAMPLE / "receipts_dirty.csv"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    ingest.validate_receipt(path)
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == after


def test_load_sample_returns_records_and_inventory():
    records, inventory = ingest.load_sample()
    assert len(records) > 2000
    assert len(inventory) == 30
    assert all("date" in row and "ts" in row for row in records[:10])
