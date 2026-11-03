"""生成测试用的假销售数据。

你拿不到真实店铺数据，但算法阶段假数据完全够用 —— 而且比真实数据更好，
因为你知道正确答案是什么，可以验证算法算得对不对。

这个脚本会故意埋入若干"连带购买关系"，跑通 Apriori 之后应该能挖出来：

    啤酒   → 花生米      花生米 → 啤酒
    可乐   → 薯片
    面包   → 牛奶
    洗发水 → 护发素
    牙膏   → 牙刷
    咖啡   → 方糖

如果挖不出这些组合，说明算法有问题。

用法：
    python tools/make_fake_data.py
"""

import csv
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"

SEED = 20261013
DAYS = 120
BASE_TRANSACTIONS_PER_DAY = 12  # 每天大概这么多张小票

# (sku_id, 名称, 品类, 成本, 售价, 人气权重, 旺季月份)
SKUS = [
    ("S001", "青岛啤酒", "饮料", 3.20, 5.50, 10, [6, 7, 8]),
    ("S002", "花生米", "零食", 2.10, 4.00, 8, []),
    ("S003", "可口可乐", "饮料", 2.00, 3.50, 12, [6, 7, 8]),
    ("S004", "乐事薯片", "零食", 3.50, 6.00, 9, []),
    ("S005", "切片面包", "烘焙", 4.00, 7.00, 7, []),
    ("S006", "光明牛奶", "乳制品", 3.80, 6.50, 11, []),
    ("S007", "海飞丝洗发水", "日用品", 15.00, 26.00, 3, []),
    ("S008", "海飞丝护发素", "日用品", 14.00, 24.00, 3, []),
    ("S009", "云南白药牙膏", "日用品", 9.00, 15.90, 4, []),
    ("S010", "软毛牙刷", "日用品", 2.50, 5.00, 4, []),
    ("S011", "雀巢速溶咖啡", "冲调", 18.00, 32.00, 3, [10, 11, 12, 1]),
    ("S012", "方糖", "冲调", 3.00, 6.00, 2, [10, 11, 12, 1]),
    ("S013", "农夫山泉", "饮料", 1.20, 2.50, 14, [6, 7, 8]),
    ("S014", "康师傅红烧牛肉面", "方便食品", 3.00, 5.50, 10, []),
    ("S015", "双汇火腿肠", "方便食品", 1.50, 3.00, 8, []),
    ("S016", "鸡蛋 10枚", "生鲜", 7.50, 11.90, 9, []),
    ("S017", "西红柿 500g", "生鲜", 3.00, 5.50, 7, [7, 8, 9]),
    ("S018", "土豆 500g", "生鲜", 2.00, 3.80, 6, []),
    ("S019", "伊利酸奶", "乳制品", 3.20, 5.80, 9, [6, 7, 8]),
    ("S020", "雀巢威化", "零食", 4.50, 8.00, 5, []),
    ("S021", "奥利奥饼干", "零食", 4.00, 7.50, 6, []),
    ("S022", "金龙鱼食用油 1L", "粮油", 12.00, 19.90, 4, []),
    ("S023", "海天生抽 500ml", "粮油", 6.00, 10.50, 4, []),
    ("S024", "洁厕灵", "日用品", 5.00, 9.90, 2, []),
    ("S025", "抽纸 3包", "日用品", 8.00, 13.90, 8, []),
    ("S026", "冰红茶", "饮料", 2.20, 4.00, 7, [6, 7, 8]),
    ("S027", "洽洽瓜子", "零食", 5.50, 9.90, 5, [1, 2, 12]),
    ("S028", "火腿三明治", "烘焙", 5.00, 9.00, 5, []),
    ("S029", "湿纸巾 80抽", "日用品", 6.50, 11.90, 4, []),
    ("S030", "进口蓝莓 125g", "生鲜", 12.00, 19.90, 1, [5, 6, 7]),
]

# 埋入的连带购买关系：(触发商品, 连带商品, 连带概率)
AFFINITY = [
    ("S001", "S002", 0.72),  # 啤酒 → 花生米
    ("S003", "S004", 0.65),  # 可乐 → 薯片
    ("S005", "S006", 0.68),  # 面包 → 牛奶
    ("S007", "S008", 0.60),  # 洗发水 → 护发素
    ("S009", "S010", 0.58),  # 牙膏 → 牙刷
    ("S011", "S012", 0.55),  # 咖啡 → 方糖
    ("S014", "S015", 0.50),  # 泡面 → 火腿肠
]

SEASONALITY = {s[0]: (s[6], s[5]) for s in SKUS}  # sku_id -> (旺季月份, 人气权重)


def weighted_choice(pool: list[str], weights: list[float]) -> str:
    total = sum(weights)
    r = random.uniform(0, total)
    acc = 0.0
    for item, w in zip(pool, weights):
        acc += w
        if r <= acc:
            return item
    return pool[-1]


def season_factor(sku_id: str, month: int) -> float:
    months, _ = SEASONALITY[sku_id]
    return 1.8 if month in months else 1.0


def generate() -> None:
    random.seed(SEED)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    sku_ids = [s[0] for s in SKUS]
    weights = [float(s[5]) for s in SKUS]
    price_of = {s[0]: s[4] for s in SKUS}

    start = date.today() - timedelta(days=DAYS - 1)
    detail_rows: list[dict] = []
    order_counter = 0

    for day_offset in range(DAYS):
        today = start + timedelta(days=day_offset)
        month = today.month
        weekday = today.weekday()

        # 周末生意好一些
        n_orders = BASE_TRANSACTIONS_PER_DAY
        if weekday >= 5:
            n_orders = int(n_orders * 1.5)
        n_orders = max(3, int(random.gauss(n_orders, n_orders * 0.25)))

        for _ in range(n_orders):
            order_counter += 1
            order_id = f"T{order_counter:05d}"
            hour = random.choices(
                [8, 10, 12, 15, 18, 19, 20, 21],
                weights=[4, 6, 8, 6, 12, 14, 12, 6],
            )[0]
            minute = random.randint(0, 59)
            ts = f"{today.isoformat()} {hour:02d}:{minute:02d}"

            # 一张小票买 1-5 种商品
            n_items = random.choices([1, 2, 3, 4, 5], weights=[30, 30, 22, 12, 6])[0]

            adjusted = [
                w * season_factor(sid, month) for sid, w in zip(sku_ids, weights)
            ]
            basket: set[str] = set()
            while len(basket) < n_items:
                basket.add(weighted_choice(sku_ids, adjusted))

            # 按埋好的关联规则追加连带商品
            for trigger, follower, prob in AFFINITY:
                if trigger in basket and follower not in basket:
                    if random.random() < prob * season_factor(follower, month) ** 0.5:
                        basket.add(follower)

            for sid in sorted(basket):
                qty = random.choices([1, 2, 3, 4], weights=[62, 22, 10, 6])[0]
                detail_rows.append(
                    {
                        "order_id": order_id,
                        "sku_id": sid,
                        "qty": qty,
                        "date": ts,
                        "unit_price": f"{price_of[sid]:.2f}",
                    }
                )

    write_csv(
        SAMPLE_DIR / "receipts.csv",
        ["order_id", "sku_id", "qty", "date", "unit_price"],
        detail_rows,
    )

    # ---- 商品档案 ----
    write_csv(
        SAMPLE_DIR / "products.csv",
        ["sku_id", "sku_name", "category", "cost", "price"],
        [
            {
                "sku_id": s[0],
                "sku_name": s[1],
                "category": s[2],
                "cost": f"{s[3]:.2f}",
                "price": f"{s[4]:.2f}",
            }
            for s in SKUS
        ],
    )

    # ---- 库存快照：故意造出"缺货的"和"压货的" ----
    # 前 6 个库存偏低（应该触发补货），后 6 个库存偏高（应该判滞销）
    sales_by_sku: dict[str, int] = defaultdict(int)
    for r in detail_rows:
        sales_by_sku[r["sku_id"]] += int(r["qty"])

    inventory_rows = []
    for idx, s in enumerate(SKUS):
        daily = sales_by_sku[s[0]] / DAYS
        if idx < 6:
            stock = max(0, int(daily * random.uniform(0.5, 2.5)))
        elif idx >= len(SKUS) - 6:
            stock = int(daily * random.uniform(60, 110))
        else:
            stock = int(daily * random.uniform(8, 25))
        inventory_rows.append(
            {
                "sku_id": s[0],
                "sku_name": s[1],
                "stock_qty": stock,
                "cost": f"{s[3]:.2f}",
            }
        )

    write_csv(
        SAMPLE_DIR / "inventory.csv",
        ["sku_id", "sku_name", "stock_qty", "cost"],
        inventory_rows,
    )

    # ---- 一份故意有问题的文件，用来测试校验功能（M1）----
    bad_rows = [
        {"order_id": "B0001", "sku_id": "S001", "qty": 2, "date": "2026-01-01 10:00", "unit_price": "5.50"},
        {"order_id": "B0002", "sku_id": "", "qty": 1, "date": "2026-01-01 11:00", "unit_price": "3.50"},       # SKU 为空
        {"order_id": "B0003", "sku_id": "S003", "qty": -2, "date": "2026-01-01 12:00", "unit_price": "3.50"},   # 数量为负
        {"order_id": "B0004", "sku_id": "S005", "qty": 1.5, "date": "2026-01-01 13:00", "unit_price": "7.00"},  # 数量非整数
        {"order_id": "B0005", "sku_id": "S006", "qty": 1, "date": "昨天下午", "unit_price": "6.50"},            # 日期非法
        {"order_id": "B0006", "sku_id": "S013", "qty": 3, "date": "2026-01-01 15:00", "unit_price": "2.50"},
    ]
    write_csv(
        SAMPLE_DIR / "receipts_dirty.csv",
        ["order_id", "sku_id", "qty", "date", "unit_price"],
        bad_rows,
    )

    # ---- 汇总 ----
    print("假数据生成完毕，位置：", SAMPLE_DIR)
    print(f"  receipts.csv        {len(detail_rows):>6} 行明细，"
          f"{order_counter} 张小票，跨度 {DAYS} 天")
    print(f"  products.csv        {len(SKUS):>6} 个 SKU")
    print(f"  inventory.csv       {len(inventory_rows):>6} 个 SKU 的库存")
    print("  receipts_dirty.csv       6 行（含 4 处故意错误，用于测试数据校验）")
    print()
    print("预期能在购物篮分析中挖出的关联关系：")
    for trigger, follower, prob in AFFINITY:
        t_name = next(s[1] for s in SKUS if s[0] == trigger)
        f_name = next(s[1] for s in SKUS if s[0] == follower)
        print(f"  {t_name} → {f_name}（埋入连带概率 {prob:.0%}）")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    generate()
