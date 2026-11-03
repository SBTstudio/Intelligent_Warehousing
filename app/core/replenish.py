"""【M4】补货预测 —— 日均消耗、安全库存、补货点、建议补货日期。

对应需求：1.1 目标 1（提供不同 SKU 的补货周期和库存量建议）、2.1 输入量 2

------------------------------------------------------------
公式
------------------------------------------------------------
    日均销量 d̄    ：对历史日销量做指数平滑或 Holt 线性趋势
                    简单移动平均版本：d̄ = 最近 N 天销量之和 / N
                    指数平滑版本：    d̄_t = α·x_t + (1-α)·d̄_{t-1}   （α 取 0.3 左右）

    需求波动 σ_d ：同一时间窗口内日销量的标准差

    安全库存 SS  = z × σ_d × √LT
        z 由服务水平决定：服务水平 95% → z = 1.65
                        服务水平 99% → z = 2.33
        LT 是供应商到货提前期（天）

    补货点 ROP   = d̄ × LT + SS
        库存降到 ROP 以下就该下单了

    剩余可售天数 = (现有库存 − SS) / d̄

    建议补货日   = 今天 + 剩余可售天数 − LT
        含义：必须在这一天之前下单，货才能接得上

    建议补货量   参考 d̄ ×（到货提前期 + 一个补货周期）+ SS − 现有库存
        （没有单次订货成本与持有成本，EOQ 无法准确计算，这里采用简化版本，
          在 README 的设计取舍里说明了假设）

    数据不足时（有效销售天数 < 7 天）会在结果里保留样本量提示，
    对应需求 2.2.3「数据样本较少时提示补充数据」。
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# 服务水平 → 安全库存系数 z（保留常见档位，缺失档位用正态分位精确计算）
SERVICE_LEVEL_Z = {
    0.90: 1.28,
    0.95: 1.65,
    0.97: 1.88,
    0.99: 2.33,
}

# 数据少于这么多天时，日均销量的可信度会明显下降
MIN_SAMPLE_DAYS = 7

# 默认一个补货周期的天数（可在界面「参数配置」里改）
DEFAULT_REPLENISH_DAYS = 7


@dataclass
class ReplenishSuggestion:
    """单个 SKU 的补货建议。"""

    sku_id: str
    sku_name: str = ""
    stock_qty: float = 0.0
    daily_sales: float = 0.0  # 日均销量 d̄
    demand_std: float = 0.0  # 需求波动 σ_d
    safety_stock: float = 0.0  # 安全库存 SS
    reorder_point: float = 0.0  # 补货点 ROP
    days_left: float = 0.0  # 剩余可售天数
    suggest_date: date | None = None  # 建议补货日期
    suggest_qty: float = 0.0  # 建议补货量
    urgent: bool = False  # 是否已低于补货点
    sample_days: int = 0  # 参与计算的有效销售天数
    note: str = ""  # 数据不足等提示


def z_for(service_level: float) -> float:
    """把服务水平换算成安全库存系数 z。

    常见档位直接查表（与需求文档给出的 1.65 / 2.33 一致），
    其他档位用正态分布分位数计算，避免维护一张无限大的表。
    """
    level = float(service_level)
    if not 0.0 < level < 1.0:
        raise ValueError("服务水平必须在 (0, 1) 区间内")

    # 浮点比较用 round 规避 0.9500000001 这类误差
    key = round(level, 4)
    if key in SERVICE_LEVEL_Z:
        return SERVICE_LEVEL_Z[key]

    from statistics import NormalDist

    return NormalDist().inv_cdf(level)


def _parse_day(value) -> date | None:
    """把各种常见日期写法转成 date；无法解析时返回 None。"""
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
    # 兼容 "2026年1月1日"
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    head = text[:10]
    try:
        return datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        return None


def _record_day(record: dict) -> date | None:
    return _parse_day(record.get("date") or record.get("ts"))


def daily_series(records: list[dict], sku_id: str) -> list[tuple[date, float]]:
    """把某 SKU 的销售记录整理成 "每天一个数据点" 的序列。

    参数
        records: [{"sku_id": "S001", "qty": 2, "date": "2026-01-01"}, ...]
    返回
        [(date(2026,1,1), 5.0), (date(2026,1,2), 3.0), ...]
        中间没有销售的日子补 0，否则日均销量会被高估、σ 会被低估。
    """
    by_day: dict[date, float] = {}
    for record in records:
        if str(record.get("sku_id")) != str(sku_id):
            continue
        day = _record_day(record)
        if day is None:
            continue
        try:
            qty = float(record.get("qty", 0) or 0)
        except (TypeError, ValueError):
            continue
        by_day[day] = by_day.get(day, 0.0) + max(0.0, qty)

    if not by_day:
        return []

    start, end = min(by_day), max(by_day)
    series: list[tuple[date, float]] = []
    cursor = start
    while cursor <= end:
        series.append((cursor, by_day.get(cursor, 0.0)))
        cursor += timedelta(days=1)
    return series


def moving_average(values: list[float], window: int = 7) -> float | None:
    """简单移动平均，取最近 window 天的平均值作为日均销量。

    数据为空或不足 window 天时返回 None，让调用方提示补充数据
    （对应需求 2.2.3），而不是用两天的数据硬算一个"日均"。
    """
    if not values or window <= 0 or len(values) < window:
        return None
    clean = [float(v) for v in values[-window:]]
    return sum(clean) / len(clean)


def exponential_smoothing(values: list[float], alpha: float = 0.3) -> float:
    """指数平滑，比简单平均更能反映近期趋势。

    d̄_t = alpha * x_t + (1 - alpha) * d̄_{t-1}

    第一个点直接作为初值；空列表返回 0.0。alpha 会被夹到 (0, 1]，
    避免误传 0 或大于 1 时把结果算成常数 / 发散。
    """
    if not values:
        return 0.0
    alpha = min(1.0, max(1e-6, float(alpha)))
    smoothed = float(values[0])
    for value in values[1:]:
        smoothed = alpha * float(value) + (1.0 - alpha) * smoothed
    return smoothed


def build_suggestion(
    sku_id: str,
    sku_name: str,
    stock_qty: float,
    values: list[float],
    lead_time_days: int,
    service_level: float = 0.95,
    today: date | None = None,
    replenish_days: int = DEFAULT_REPLENISH_DAYS,
) -> ReplenishSuggestion:
    """核心函数：给定一个 SKU 的库存和日销量序列，算出完整补货建议。

    计算顺序：
        d̄  = exponential_smoothing(values)
        σ_d = 总体标准差(values)
        z   = z_for(service_level)
        SS  = z * σ_d * sqrt(lead_time_days)
        ROP = d̄ * lead_time_days + SS
        剩余可售天数 = (stock_qty - SS) / d̄
        建议补货日 = today + 剩余可售天数 - lead_time_days
        urgent = stock_qty <= ROP

    特殊情况：d̄ = 0 说明商品压根没卖动，不做补货建议（转滞销处理），
    避免除零；此时 urgent=False、建议日期为空。
    """
    today = today or date.today()
    lead_time = max(0, int(lead_time_days))
    stock = max(0.0, float(stock_qty))
    clean = [float(v) for v in values if v is not None]

    if clean:
        daily = exponential_smoothing(clean)
        # 用总体标准差：描述"这个 SKU 过去这些天的波动"本身，而不是抽样推断
        sigma = statistics.pstdev(clean) if len(clean) > 1 else 0.0
    else:
        daily, sigma = 0.0, 0.0

    z = z_for(service_level)
    safety_stock = z * sigma * math.sqrt(lead_time)
    reorder_point = daily * lead_time + safety_stock

    note = ""
    if len(clean) < MIN_SAMPLE_DAYS:
        note = f"仅 {len(clean)} 天有效销售数据，建议补充更多数据后重算"

    if daily <= 1e-9:
        return ReplenishSuggestion(
            sku_id=sku_id,
            sku_name=sku_name,
            stock_qty=round(stock, 2),
            daily_sales=0.0,
            demand_std=round(sigma, 3),
            safety_stock=round(safety_stock, 3),
            reorder_point=round(reorder_point, 3),
            days_left=999.0,
            suggest_date=None,
            suggest_qty=0.0,
            urgent=False,
            sample_days=len(clean),
            note=note or "近期无销售，按滞销商品处理",
        )

    days_left = (stock - safety_stock) / daily
    suggest_date = today + timedelta(days=days_left - lead_time)
    # 建议量 = 覆盖一个「到货提前期 + 补货周期」的需求 + 安全库存 - 现有库存
    target_stock = daily * (lead_time + max(1, int(replenish_days))) + safety_stock
    suggest_qty = max(0.0, target_stock - stock)

    return ReplenishSuggestion(
        sku_id=sku_id,
        sku_name=sku_name,
        stock_qty=round(stock, 2),
        daily_sales=round(daily, 3),
        demand_std=round(sigma, 3),
        safety_stock=round(safety_stock, 3),
        reorder_point=round(reorder_point, 3),
        days_left=round(days_left, 1),
        suggest_date=suggest_date,
        suggest_qty=float(math.ceil(suggest_qty)),
        urgent=stock <= reorder_point,
        sample_days=len(clean),
        note=note,
    )


def build_all_suggestions(
    sales_records: list[dict],
    inventory: list[dict],
    lead_time_days: int = 3,
    service_level: float = 0.95,
    replenish_days: int = DEFAULT_REPLENISH_DAYS,
    today: date | None = None,
) -> list[ReplenishSuggestion]:
    """批量入口：对所有 SKU 生成补货建议，按紧急程度排序。

    参数
        sales_records: 销售明细
        inventory:     [{"sku_id": "S001", "sku_name": "可乐", "stock_qty": 40}, ...]
    返回
        list[ReplenishSuggestion]，urgent 的排前面，其次按剩余可售天数升序
    """
    # 先按 SKU 分组，避免对每个 SKU 都全量扫一遍销售明细（O(SKU × 行数)）
    grouped: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for record in sales_records:
        sku = str(record.get("sku_id", "")).strip()
        if not sku:
            continue
        grouped.setdefault(sku, []).append(record)
        if record.get("sku_name") and sku not in names:
            names[sku] = str(record["sku_name"])

    stock_map: dict[str, float] = {}
    for row in inventory:
        sku = str(row.get("sku_id", "")).strip()
        if not sku:
            continue
        try:
            stock_map[sku] = max(0.0, float(row.get("stock_qty", 0) or 0))
        except (TypeError, ValueError):
            stock_map[sku] = 0.0
        if row.get("sku_name"):
            names[sku] = str(row["sku_name"])

    all_skus = sorted(set(stock_map) | set(grouped))
    suggestions: list[ReplenishSuggestion] = []
    for sku in all_skus:
        series = daily_series(grouped.get(sku, []), sku)
        values = [qty for _, qty in series]
        suggestions.append(
            build_suggestion(
                sku_id=sku,
                sku_name=names.get(sku, ""),
                stock_qty=stock_map.get(sku, 0.0),
                values=values,
                lead_time_days=lead_time_days,
                service_level=service_level,
                today=today,
                replenish_days=replenish_days,
            )
        )

    suggestions.sort(key=lambda s: (0 if s.urgent else 1, s.days_left, -s.daily_sales))
    return suggestions
