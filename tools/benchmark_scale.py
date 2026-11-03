"""【容量实测】验证 SQLite 能否扛住三年经营数据。

用途：需求文档 2.5 要求"支持保存至少 N 年店铺销售历史数据"，
      这个脚本用真实数据量测一遍，把"能不能存得下、查得快不快"变成实测数字，
      而不是拍脑袋估算。答辩时可以直接拿这份结果说话。

它测两件事：
    1. 容量：插入三年数据后，数据库文件多大
    2. 性能：几条典型分析查询各耗时多少（对应需求 1.1 的"小数据集≤3s、较大数据集≤15s"）

用法：
    python tools/benchmark_scale.py
    python tools/benchmark_scale.py --sku 500 --orders 300 --days 1095   # 压力场景

生成的 bench.db 是独立的测试文件，不会污染正式的 data/app.db。
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH_DB = ROOT / "data" / "bench.db"

SCHEMA = """
CREATE TABLE products (
    sku_id TEXT PRIMARY KEY, sku_name TEXT, category TEXT, cost REAL, price REAL
);
CREATE TABLE transactions (
    order_id TEXT PRIMARY KEY, ts TEXT NOT NULL, total_amount REAL NOT NULL
);
CREATE INDEX idx_tx_ts ON transactions(ts);
CREATE TABLE transaction_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL, sku_id TEXT NOT NULL, qty INTEGER NOT NULL, unit_price REAL NOT NULL
);
CREATE INDEX idx_item_order ON transaction_items(order_id);
CREATE INDEX idx_item_sku ON transaction_items(sku_id);
CREATE TABLE inventory (
    sku_id TEXT NOT NULL, snapshot_date TEXT NOT NULL, stock_qty REAL NOT NULL, cost REAL NOT NULL,
    PRIMARY KEY (sku_id, snapshot_date)
);
CREATE INDEX idx_inv_sku_stock ON inventory(sku_id, stock_qty);
"""

CATEGORIES = ["饮料", "零食", "乳制品", "日用品", "粮油", "生鲜", "方便食品", "烘焙", "冲调"]


def make_products(n: int) -> list[tuple]:
    rng = random.Random(42)
    rows = []
    for i in range(1, n + 1):
        cat = rng.choice(CATEGORIES)
        cost = round(rng.uniform(1.0, 20.0), 2)
        rows.append((f"S{i:05d}", f"商品{i:05d}", cat, cost, round(cost * rng.uniform(1.4, 2.2), 2)))
    return rows


def generate(days: int, sku_n: int, orders_per_day: int, seed: int = 20261013):
    """惰性生成器：逐日产出 (transactions, items, inventory) 三元组，避免一次性占满内存。"""
    rng = random.Random(seed)
    sku_ids = [f"S{i:05d}" for i in range(1, sku_n + 1)]
    price_of = {f"S{i:05d}": round(1.0 + (i % 17) * 0.9, 2) for i in range(1, sku_n + 1)}
    start = date.today() - timedelta(days=days - 1)
    order_no = 0

    for d in range(days):
        day = start + timedelta(days=d)
        weekday = day.weekday()
        n = int(orders_per_day * (1.5 if weekday >= 5 else 1.0) * rng.uniform(0.85, 1.15))
        tx_rows, item_rows = [], []
        for _ in range(n):
            order_no += 1
            oid = f"T{order_no:08d}"
            hour = rng.choice([8, 10, 12, 15, 18, 19, 20, 21])
            ts = f"{day.isoformat()} {hour:02d}:{rng.randint(0, 59):02d}"
            k = rng.choices([1, 2, 3, 4, 5, 6], weights=[28, 28, 20, 12, 7, 5])[0]
            basket = rng.sample(sku_ids, min(k, sku_n))
            total = 0.0
            for sid in basket:
                qty = rng.choices([1, 2, 3, 4], weights=[62, 22, 10, 6])[0]
                total += qty * price_of[sid]
                item_rows.append((oid, sid, qty, price_of[sid]))
            tx_rows.append((oid, ts, round(total, 2)))

        inv_rows = [
            (sid, day.isoformat(), float(rng.randint(0, 120)), round(rng.uniform(1.0, 20.0), 2))
            for sid in sku_ids
        ]
        yield tx_rows, item_rows, inv_rows


def build(days: int, sku_n: int, orders_per_day: int) -> dict:
    if BENCH_DB.exists():
        BENCH_DB.unlink()
    BENCH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(BENCH_DB)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")

    with conn:
        conn.executemany("INSERT INTO products VALUES (?,?,?,?,?)", make_products(sku_n))

    t0 = time.perf_counter()
    n_tx = n_item = n_inv = 0
    with conn:
        for tx_rows, item_rows, inv_rows in generate(days, sku_n, orders_per_day):
            conn.executemany("INSERT INTO transactions VALUES (?,?,?)", tx_rows)
            conn.executemany("INSERT INTO transaction_items (order_id,sku_id,qty,unit_price) VALUES (?,?,?,?)", item_rows)
            conn.executemany("INSERT INTO inventory VALUES (?,?,?,?)", inv_rows)
            n_tx += len(tx_rows)
            n_item += len(item_rows)
            n_inv += len(inv_rows)
    insert_s = time.perf_counter() - t0
    # 关键一步：没有统计信息，SQLite 在三年数据量下会选错执行计划（详见 schema.analyze 说明）
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()
    return {
        "days": days, "sku": sku_n, "tx": n_tx, "items": n_item, "inv": n_inv,
        "insert_s": insert_s, "size_mb": BENCH_DB.stat().st_size / 1024 / 1024,
    }


def timed(conn: sqlite3.Connection, label: str, sql: str, args: tuple = ()) -> tuple[str, float, int]:
    t0 = time.perf_counter()
    rows = conn.execute(sql, args).fetchall()
    return label, (time.perf_counter() - t0) * 1000, len(rows)


def benchmark() -> list[tuple[str, float, int]]:
    conn = sqlite3.connect(BENCH_DB)
    today = date.today()
    win90 = (today - timedelta(days=90)).isoformat()
    win365 = (today - timedelta(days=365)).isoformat()
    out = [
        # 对应 Apriori 购物篮分析：取最近 90 天的小票明细
        timed(conn, "购物篮明细提取（近90天）",
              "SELECT i.order_id, i.sku_id FROM transaction_items i JOIN transactions t "
              "ON t.order_id=i.order_id WHERE t.ts >= ?", (win90,)),
        # 对应补货模型：单个 SKU 的日销量序列
        timed(conn, "单 SKU 日销量序列（近90天）",
              "SELECT substr(t.ts,1,10) d, SUM(i.qty) q FROM transaction_items i JOIN transactions t "
              "ON t.order_id=i.order_id WHERE i.sku_id=? AND t.ts>=? GROUP BY d ORDER BY d",
              ("S00001", win90)),
        # 对应 ABC 分析：按 SKU 汇总一年销售额
        timed(conn, "ABC 销售额汇总（近365天）",
              "SELECT i.sku_id, SUM(i.qty*i.unit_price) amt FROM transaction_items i JOIN transactions t "
              "ON t.order_id=i.order_id WHERE t.ts>=? GROUP BY i.sku_id ORDER BY amt DESC", (win365,)),
        # 对应滞销判定：全周期库存快照聚合
        timed(conn, "全周期库存快照聚合",
              "SELECT sku_id, AVG(stock_qty) FROM inventory GROUP BY sku_id"),
        # 最坏情况：不分窗口，全量拉取
        timed(conn, "全量销售明细拉取（无窗口）",
              "SELECT i.order_id, t.ts, i.sku_id, i.qty, i.unit_price FROM transaction_items i "
              "JOIN transactions t ON t.order_id=i.order_id"),
    ]
    conn.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1095, help="天数，默认 3 年（1095）")
    ap.add_argument("--sku", type=int, default=300, help="SKU 数量，默认 300")
    ap.add_argument("--orders", type=int, default=100, help="日均小票数，默认 100")
    args = ap.parse_args()

    print(f"正在生成 {args.days} 天 × {args.sku} SKU × 日均 {args.orders} 张小票 ……")
    info = build(args.days, args.sku, args.orders)

    print("\n" + "=" * 62)
    print(f"容量结果（跨期 {info['days']} 天 ≈ {info['days']/365:.1f} 年）")
    print("=" * 62)
    print(f"  小票数          {info['tx']:>12,} 行")
    print(f"  销售明细        {info['items']:>12,} 行")
    print(f"  库存快照        {info['inv']:>12,} 行")
    print(f"  合计            {info['tx']+info['items']+info['inv']:>12,} 行")
    print(f"  数据库文件大小  {info['size_mb']:>12.1f} MB")
    print(f"  批量导入耗时    {info['insert_s']:>12.1f} 秒")

    print("\n" + "=" * 62)
    print("查询性能（需求 1.1：小数据集≤3s，较大数据集≤15s）")
    print("=" * 62)
    for label, ms, n in benchmark():
        verdict = "✅ 达标" if ms < 3000 else ("⚠️ 偏慢" if ms < 15000 else "❌ 超时")
        print(f"  {label:<26s} {ms:>9.0f} ms  ({n:,} 行)  {verdict}")

    print(f"\n测试库：{BENCH_DB}")
    print("（这是独立测试文件，不影响 data/app.db；确认无用后可直接删除）")


if __name__ == "__main__":
    sys.exit(main())
