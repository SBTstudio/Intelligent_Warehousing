"""【M5】畅销 / 滞销判定 —— ABC × XYZ 交叉分类。

对应需求：2.1 输入量 2
    "输出预期补货时间、滞销商品/畅销商品统计、换季商品推荐。"

------------------------------------------------------------
ABC 分类（按销售额贡献）
------------------------------------------------------------
    把所有 SKU 按销售额从高到低排序，算累计占比：
        累计占比 ≤ 70%  → A 类（核心商品，贡献大头）
        70% < 累计 ≤ 90% → B 类（中坚）
        累计 > 90%       → C 类（长尾）

------------------------------------------------------------
XYZ 分类（按需求稳定性）
------------------------------------------------------------
    变异系数 CV = σ / μ   （σ = 日销量标准差，μ = 日均销量）
        CV < 0.2        → X 类（需求平稳，好预测）
        0.2 ≤ CV < 0.5  → Y 类（有波动，季节性明显）
        CV ≥ 0.5        → Z 类（极不稳定，随机性强）

------------------------------------------------------------
判定规则
------------------------------------------------------------
    滞销：C 类 且 Z 类 且 周转天数 > 阈值
          周转天数 = 现有库存 / 日均销量
    呆滞：C 类 且 周转天数 > 2 × 阈值（比滞销更严重，优先判定）
    畅销：A 类
    正常：其余

    为什么用 ABC × XYZ 而不是单一销量阈值：
    单看销量会把"卖得多但经常断货"和"卖得少但很稳定"混为一谈；
    ABC 看贡献、XYZ 看稳定性，两者交叉后才能区分"核心畅销"、
    "稳定长尾"、"高波动滞销"这些经营含义完全不同的商品。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime

# ABC 分类的累计占比分界
ABC_THRESHOLDS = (0.70, 0.90)

# XYZ 分类的变异系数分界
XYZ_THRESHOLDS = (0.2, 0.5)

# 无销售商品的周转天数用一个很大的值表示，避免除零
NO_SALES_TURNOVER = 99999.0


@dataclass
class SkuProfile:
    """单个 SKU 的分类结果。"""

    sku_id: str
    sku_name: str = ""
    sales_amount: float = 0.0  # 销售额
    sales_amount_ratio: float = 0.0  # 占总销售额比例
    cumulative_ratio: float = 0.0  # 累计占比
    abc_class: str = ""  # A / B / C
    mean_sales: float = 0.0  # 日均销量 μ
    std_sales: float = 0.0  # 日销量标准差 σ
    cv: float = 0.0  # 变异系数
    xyz_class: str = ""  # X / Y / Z
    turnover_days: float = 0.0  # 周转天数
    verdict: str = ""  # 畅销 / 正常 / 滞销 / 呆滞


def abc_classify(profiles: list[SkuProfile]) -> list[SkuProfile]:
    """按销售额做 ABC 分类，返回按销售额降序排列的列表。

    处理要点：
      - 销售额为 0 的商品直接归 C（不参与累计占比的分档）
      - 累计占比用"包含当前商品"的口径，即第一件商品就按自己的占比判断
    """
    if not profiles:
        return []

    ordered = sorted(profiles, key=lambda p: p.sales_amount, reverse=True)
    total = sum(max(0.0, p.sales_amount) for p in ordered)

    cumulative = 0.0
    a_line, b_line = ABC_THRESHOLDS
    for profile in ordered:
        if total <= 0 or profile.sales_amount <= 0:
            profile.sales_amount_ratio = 0.0
            profile.abc_class = "C"
        else:
            ratio = profile.sales_amount / total
            profile.sales_amount_ratio = ratio
            cumulative += ratio
            if cumulative <= a_line:
                profile.abc_class = "A"
            elif cumulative <= b_line:
                profile.abc_class = "B"
            else:
                profile.abc_class = "C"
        profile.cumulative_ratio = cumulative
    return ordered


def xyz_classify(values: list[float]) -> tuple[float, str]:
    """根据日销量序列判断 XYZ 类别，返回 (cv, 类别)。

    μ 为 0（完全卖不动）时直接判 Z；空序列也按 Z 处理。
    """
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return 0.0, "Z"

    mean = sum(clean) / len(clean)
    if abs(mean) < 1e-12:
        return 0.0, "Z"

    sigma = statistics.pstdev(clean) if len(clean) > 1 else 0.0
    cv = abs(sigma / mean)
    x_line, y_line = XYZ_THRESHOLDS
    if cv < x_line:
        return cv, "X"
    if cv < y_line:
        return cv, "Y"
    return cv, "Z"


def judge(profile: SkuProfile, slow_turnover_days: int = 45) -> str:
    """综合 ABC 与 XYZ 给出最终判定。

    顺序很重要：先判更严重的呆滞，再判滞销，最后才判畅销，
    避免一个"库存压了两年"的 C 类商品因为某个条件被误判成正常。
    """
    threshold = max(1, int(slow_turnover_days))
    if profile.abc_class == "C" and profile.turnover_days > threshold * 2:
        return "呆滞"
    if (
        profile.abc_class == "C"
        and profile.xyz_class == "Z"
        and profile.turnover_days > threshold
    ):
        return "滞销"
    if profile.abc_class == "A":
        return "畅销"
    return "正常"


def _parse_day(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("/", "-").replace(".", "-")
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def analyze(
    sales_records: list[dict],
    inventory: list[dict],
    slow_turnover_days: int = 45,
) -> list[SkuProfile]:
    """主入口：对全部 SKU 做 ABC × XYZ 分类并判定。

    参数
        sales_records: [{"sku_id","sku_name","qty","unit_price","date"}, ...]
        inventory:     [{"sku_id","stock_qty"}, ...]
    返回
        list[SkuProfile]，按销售额降序

    实现要点：
      1. 先确定全局日期范围，再为每个 SKU 生成等长的日销量序列（缺日补 0）；
         这样不同 SKU 的 μ、σ、CV 才可比。
      2. 日均销量用"总销量 / 覆盖天数"，而不是"总销量 / 有销售的天数"。
      3. 库存来自最新快照；没有销售的 SKU 也会出现在结果里（判呆滞）。
    """
    names: dict[str, str] = {}
    amount: dict[str, float] = {}
    qty_by_day: dict[str, dict[date, float]] = {}
    days: set[date] = set()

    for record in sales_records:
        sku = str(record.get("sku_id", "")).strip()
        if not sku:
            continue
        day = _parse_day(record.get("date") or record.get("ts"))
        if day is None:
            continue
        try:
            qty = max(0.0, float(record.get("qty", 0) or 0))
        except (TypeError, ValueError):
            qty = 0.0
        try:
            price = float(record.get("unit_price", 0) or 0)
        except (TypeError, ValueError):
            price = 0.0
        if record.get("sku_name") and sku not in names:
            names[sku] = str(record["sku_name"])

        amount[sku] = amount.get(sku, 0.0) + qty * price
        qty_by_day.setdefault(sku, {})
        qty_by_day[sku][day] = qty_by_day[sku].get(day, 0.0) + qty
        days.add(day)

    stock: dict[str, float] = {}
    for row in inventory:
        sku = str(row.get("sku_id", "")).strip()
        if not sku:
            continue
        try:
            stock[sku] = max(0.0, float(row.get("stock_qty", 0) or 0))
        except (TypeError, ValueError):
            stock[sku] = 0.0
        if row.get("sku_name"):
            names[sku] = str(row["sku_name"])

    ordered_days = sorted(days)
    n_days = len(ordered_days)
    all_skus = sorted(set(qty_by_day) | set(stock))

    profiles: list[SkuProfile] = []
    for sku in all_skus:
        per_day = qty_by_day.get(sku, {})
        values = [per_day.get(day, 0.0) for day in ordered_days]
        mean = sum(values) / n_days if n_days else 0.0
        sigma = statistics.pstdev(values) if len(values) > 1 else 0.0
        cv, xyz = xyz_classify(values)
        stock_qty = stock.get(sku, 0.0)
        turnover = stock_qty / mean if mean > 1e-12 else NO_SALES_TURNOVER

        profile = SkuProfile(
            sku_id=sku,
            sku_name=names.get(sku, ""),
            sales_amount=round(amount.get(sku, 0.0), 2),
            mean_sales=round(mean, 3),
            std_sales=round(sigma, 3),
            cv=round(cv, 4),
            xyz_class=xyz,
            turnover_days=round(turnover, 1),
        )
        profiles.append(profile)

    profiles = abc_classify(profiles)
    for profile in profiles:
        profile.verdict = judge(profile, slow_turnover_days=slow_turnover_days)
    return profiles


def summary(profiles: list[SkuProfile]) -> dict:
    """统计汇总，供图表和报告使用。

    返回
        {
            "畅销": [...], "滞销": [...], "呆滞": [...], "正常": [...],
            "abc_dist": {"A": 12, "B": 30, "C": 58},
            "xyz_dist": {"X": 40, "Y": 35, "Z": 25},
        }
    """
    result: dict = {
        "畅销": [],
        "滞销": [],
        "呆滞": [],
        "正常": [],
        "abc_dist": {"A": 0, "B": 0, "C": 0},
        "xyz_dist": {"X": 0, "Y": 0, "Z": 0},
    }
    for profile in profiles:
        if profile.verdict in result:
            result[profile.verdict].append(profile)
        if profile.abc_class in result["abc_dist"]:
            result["abc_dist"][profile.abc_class] += 1
        if profile.xyz_class in result["xyz_dist"]:
            result["xyz_dist"][profile.xyz_class] += 1
    return result
