"""【M12】换季趋势分析与商品推荐。

对应需求：2.1 输入量 2（换季商品推荐）、1.1 目标 3

------------------------------------------------------------
方法
------------------------------------------------------------
    同比 YoY  = (本期销量 − 去年同期销量) / 去年同期销量
    环比 MoM  = (本月销量 − 上月销量) / 上月销量
    趋势斜率  ：对近 12 个月的月销量做一元线性回归，斜率 > 0 说明在上升

    季节指数  = 某月平均销量 / 全年月均销量
        季节指数 > 1.2 说明这个月是该商品的旺季
        跨商品比较季节指数，就能找出"哪些品类该在几月上架"

为什么值得保留三年数据：
    同比必须有去年同月的数据才能算；只有一年数据时 yoy() 会诚实地返回 None，
    而不是拿 0 当分母硬算一个假数字。

工作项：M12，属于 P2 加分项。算法负责判断趋势，LLM 只负责把结论写成人话。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime


def _month_key(value) -> str | None:
    """把记录里的日期转成 YYYY-MM。"""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m")
    text = str(value or "").strip()
    if len(text) < 7:
        return None
    text = text.replace("/", "-").replace(".", "-")
    try:
        datetime.strptime(text[:7], "%Y-%m")
    except ValueError:
        return None
    return text[:7]


def _shift_month(month: str, delta: int) -> str:
    """YYYY-MM 加减若干个月。"""
    year, mon = int(month[:4]), int(month[5:7])
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def monthly_series(records: list[dict], sku_id: str | None = None) -> dict[str, float]:
    """按月聚合销量。

    返回 {"2026-01": 120.0, "2026-02": 98.0, ...}
    sku_id 为 None 时统计全部商品。
    """
    buckets: dict[str, float] = defaultdict(float)
    for record in records:
        if sku_id is not None and str(record.get("sku_id")) != str(sku_id):
            continue
        month = _month_key(record.get("date") or record.get("ts"))
        if month is None:
            continue
        try:
            qty = float(record.get("qty", 0) or 0)
        except (TypeError, ValueError):
            continue
        buckets[month] += max(0.0, qty)
    return {month: buckets[month] for month in sorted(buckets)}


def yoy(series: dict[str, float], month: str) -> float | None:
    """同比。去年同期没有数据时返回 None（不要硬算成 0）。"""
    if month not in series:
        return None
    previous = _shift_month(month, -12)
    if previous not in series:
        return None
    base = series[previous]
    if abs(base) < 1e-12:
        return None
    return (series[month] - base) / base


def mom(series: dict[str, float], month: str) -> float | None:
    """环比。上月没有数据时返回 None。"""
    if month not in series:
        return None
    previous = _shift_month(month, -1)
    if previous not in series:
        return None
    base = series[previous]
    if abs(base) < 1e-12:
        return None
    return (series[month] - base) / base


def trend_slope(series: dict[str, float]) -> float:
    """对月销量序列做一元线性回归，返回斜率。

    用最小二乘公式手算，不引入 numpy，保证算法层零重依赖。
    少于 2 个月的数据无法判断趋势，返回 0.0。
    """
    months = sorted(series)
    if len(months) < 2:
        return 0.0
    y = [float(series[m]) for m in months]
    n = len(y)
    x_mean = (n - 1) / 2.0
    y_mean = sum(y) / n
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator <= 0:
        return 0.0
    numerator = sum((i - x_mean) * (y[i] - y_mean) for i in range(n))
    return numerator / denominator


def seasonal_index(series: dict[str, float]) -> dict[int, float]:
    """计算 1-12 月的季节指数。

    返回 {1: 0.85, 2: 0.78, ..., 7: 1.42, ...}
    指数 > 1.2 的月份就是旺季；没有数据的月份给中性值 1.0。
    """
    by_month: dict[int, list[float]] = defaultdict(list)
    for month, value in series.items():
        try:
            mon = int(month[5:7])
        except (ValueError, IndexError):
            continue
        if 1 <= mon <= 12:
            by_month[mon].append(float(value))

    all_values = [v for values in by_month.values() for v in values]
    overall = sum(all_values) / len(all_values) if all_values else 0.0
    result = {month: 1.0 for month in range(1, 13)}
    if abs(overall) < 1e-12:
        return result

    for mon, values in by_month.items():
        result[mon] = round((sum(values) / len(values)) / overall, 4)
    return result


def _bounded(value: float, limit: float = 1.0) -> float:
    """把异常大的同比 / 环比压到 [-limit, limit]，避免一个极端值支配排序。"""
    return max(-limit, min(limit, float(value)))


def recommend(records: list[dict], current_month: int) -> list[dict]:
    """给出换季推荐。

    返回形如：
        [{"sku_id": "S001", "reason": "近 3 个月持续上升，且历史 7 月为旺季",
          "action": "加大备货"}, ...]

    评分由四部分组成：
        45%  下个月的历史季节指数
        25%  最近一个月环比
        20%  最近一个月同比（没有去年数据时为 0，不惩罚）
        10%  月销量趋势斜率（按近期均值归一化）

    这是纯规则评分，结果可解释、可复现；LLM 只负责把它润色成人话。
    """
    try:
        month = int(current_month)
    except (TypeError, ValueError):
        raise ValueError("current_month 必须是 1-12 的整数") from None
    if not 1 <= month <= 12:
        raise ValueError("current_month 必须是 1-12 的整数")

    grouped: dict[str, list[dict]] = defaultdict(list)
    names: dict[str, str] = {}
    for record in records:
        sku = str(record.get("sku_id", "")).strip()
        if not sku:
            continue
        grouped[sku].append(record)
        if record.get("sku_name") and sku not in names:
            names[sku] = str(record["sku_name"])

    next_month = month % 12 + 1
    results: list[dict] = []

    for sku, rows in grouped.items():
        series = monthly_series(rows)
        if not series:
            continue
        values = list(series.values())
        if sum(values) <= 0:
            continue

        index = seasonal_index(series)
        next_index = index.get(next_month, 1.0)
        latest_month = max(series)
        mom_value = mom(series, latest_month)
        yoy_value = yoy(series, latest_month)
        slope = trend_slope(series)
        recent = values[-3:]
        recent_mean = sum(recent) / len(recent) if recent else 0.0
        slope_ratio = slope / recent_mean if abs(recent_mean) > 1e-9 else 0.0

        score = (
            0.45 * (next_index - 1.0)
            + 0.25 * _bounded(mom_value or 0.0)
            + 0.20 * _bounded(yoy_value or 0.0)
            + 0.10 * _bounded(slope_ratio)
        )

        reasons: list[str] = []
        if next_index >= 1.15:
            reasons.append(f"历史 {next_month} 月为旺季（季节指数 {next_index:.2f}）")
        elif next_index <= 0.85:
            reasons.append(f"历史 {next_month} 月为淡季（季节指数 {next_index:.2f}）")
        if mom_value is not None and mom_value >= 0.03:
            reasons.append(f"最近一个月环比 +{mom_value:.1%}")
        elif mom_value is not None and mom_value <= -0.03:
            reasons.append(f"最近一个月环比 {mom_value:.1%}")
        if yoy_value is not None and yoy_value >= 0.05:
            reasons.append(f"同比增长 +{yoy_value:.1%}")
        elif yoy_value is not None and yoy_value <= -0.05:
            reasons.append(f"同比下降 {yoy_value:.1%}")
        if slope_ratio >= 0.05:
            reasons.append("近几个月的月销量趋势向上")
        if not reasons:
            reasons.append("销量平稳，暂无明显季节信号")

        if score >= 0.25:
            action = "加大备货"
        elif score >= 0.05:
            action = "小幅增加备货"
        elif score > -0.05:
            action = "维持现状"
        else:
            action = "控制进货"

        results.append(
            {
                "sku_id": sku,
                "sku_name": names.get(sku, ""),
                "score": round(score, 4),
                "next_month_index": next_index,
                "reason": "；".join(reasons),
                "action": action,
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results
