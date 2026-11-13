"""导入模板：中文表头 + UTF-8 BOM，Excel 双击直接打开。

模板只写表头，不写示例数据，避免用户忘记删除示例行。
日期建议格式：2026-11-13 或 2026-11-13 15:30。
"""

from __future__ import annotations

import csv
from pathlib import Path

TEMPLATE_HEADERS = {
    "receipt": ["订单号", "商品编号", "商品名称", "数量", "交易时间", "单价"],
    "inventory": ["商品编号", "商品名称", "库存数量", "进货成本", "快照时间"],
    "products": ["商品编号", "商品名称", "品类", "进货成本", "零售价格"],
}

TEMPLATE_LABELS = {
    "receipt": "小票",
    "inventory": "库存",
    "products": "商品档案",
}

TEMPLATE_FILENAMES = {
    "receipt": "小票模板.csv",
    "inventory": "库存模板.csv",
    "products": "商品档案模板.csv",
}


def write_template(kind: str, path: str | Path) -> Path:
    """写出指定类型的空白 CSV 模板，返回实际路径。"""
    if kind not in TEMPLATE_HEADERS:
        raise ValueError(f"未知模板类型：{kind}")
    target = Path(path)
    if target.suffix.lower() not in (".csv", ".txt"):
        target = target.with_suffix(".csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(TEMPLATE_HEADERS[kind])
    return target
