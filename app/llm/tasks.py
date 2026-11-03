"""【M8】六个 LLM 任务函数。

每个函数负责：准备聚合摘要 → 套 Prompt 模板 → 调模型 → 校验结果 → 失败时降级。

重要纪律（写代码时反复提醒自己）：
    LLM 只接收聚合后的摘要，不接收原始明细。
    所有数字都已经由 app/core/ 算好，LLM 一个数字都不能算。
    每个函数都必须有降级路径 —— 模型挂了不能白屏。

返回值约定：
    除 explain_anomaly 外，所有函数返回 (结果, 是否真实模型输出)。
    第二个值为 False 时，前端必须显示「基础统计模式」提示。
"""

from __future__ import annotations

from datetime import datetime

from app.llm import prompts
from app.llm.client import LLMUnavailable, get_client


def _num(value, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "0"


def _replenish_line(item) -> str:
    name = getattr(item, "sku_name", "") or getattr(item, "sku_id", "")
    sku = getattr(item, "sku_id", "")
    stock = _num(getattr(item, "stock_qty", 0), 0)
    daily = _num(getattr(item, "daily_sales", 0), 2)
    days = _num(getattr(item, "days_left", 0), 1)
    quantity = _num(getattr(item, "suggest_qty", 0), 0)
    suggest_date = getattr(item, "suggest_date", None)
    date_text = suggest_date.strftime("%m-%d") if suggest_date else "尽快"
    return (
        f"- {name}（{sku}）：库存 {stock}，日均 {daily}，剩余约 {days} 天，"
        f"建议 {date_text} 前补 {quantity}"
    )


def _profile_line(item) -> str:
    name = getattr(item, "sku_name", "") or getattr(item, "sku_id", "")
    return (
        f"- {name}（{getattr(item, 'sku_id', '')}）：销售额 {_num(getattr(item, 'sales_amount', 0))} 元，"
        f"占比 {_num(getattr(item, 'sales_amount_ratio', 0) * 100, 2)}%，"
        f"{getattr(item, 'abc_class', '-')} 类 / {getattr(item, 'xyz_class', '-')} 类，"
        f"周转 {_num(getattr(item, 'turnover_days', 0), 1)} 天，判定：{getattr(item, 'verdict', '-')}"
    )


def _join(lines: list[str], empty: str = "暂无") -> str:
    return "\n".join(lines) if lines else empty


def _slow_profiles(profiles: list) -> list:
    return [p for p in profiles if getattr(p, "verdict", "") in ("滞销", "呆滞")]


def generate_report(
    replenish: list,
    profiles: list,
    rules: list,
    period: str = "本周",
    sample_size: int = 0,
) -> tuple[str, bool]:
    """L1 经营周报解读。

    返回 (报告正文, 是否为真实模型输出)
        —— 第二个值很重要：前端要据此显示"基础统计模式"提示。
    """
    replenish = list(replenish or [])
    profiles = list(profiles or [])
    rules = list(rules or [])

    urgent = [s for s in replenish if getattr(s, "urgent", False)]
    best = sorted(profiles, key=lambda p: getattr(p, "sales_amount", 0), reverse=True)[:5]
    slow = _slow_profiles(profiles)[:5]
    top_rules = sorted(
        [r for r in rules if getattr(r, "lift", 0) > 1],
        key=lambda r: getattr(r, "lift", 0),
        reverse=True,
    )[:5]

    sku_count = len(profiles)
    sample = sample_size or sku_count
    analysis_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    user_prompt = prompts.REPORT_USER.format(
        period=period,
        analysis_time=analysis_time,
        sample_size=sample,
        sku_count=sku_count,
        urgent_count=len(urgent),
        replenish_lines=_join([_replenish_line(s) for s in urgent[:8]], "本周期没有需要补货的商品"),
        best_sellers=_join([_profile_line(p) for p in best]),
        slow_count=len(slow),
        slow_movers=_join([_profile_line(p) for p in slow], "本周期没有滞销商品"),
        association_lines=_join(
            [
                f"- {r.antecedent} → {r.consequent}：支持度 {r.support:.3f}，"
                f"置信度 {r.confidence:.3f}，提升度 {r.lift:.3f}"
                for r in top_rules
            ],
            "本周期样本不足，暂无显著关联",
        ),
    )

    client = get_client()
    try:
        text = client.chat(prompts.REPORT_SYSTEM, user_prompt)
        return text.strip(), True
    except LLMUnavailable as exc:
        reason = client.degrade_reason() or str(exc)
    except Exception as exc:  # 任何意外都不能让界面崩掉
        reason = f"模型调用异常：{exc}"

    # ---------------- 降级：模板拼装 ----------------
    total_sales = sum(getattr(p, "sales_amount", 0) for p in profiles)
    a_count = sum(1 for p in profiles if getattr(p, "abc_class", "") == "A")
    urgent_text = _join([_replenish_line(s) for s in urgent[:5]], "暂无紧急补货")
    slow_text = _join(
        [f"{p.sku_name or p.sku_id}（{p.verdict}）" for p in slow], "暂无滞销商品"
    )
    relation_text = _join(
        [f"{r.antecedent} + {r.consequent}（lift {r.lift:.2f}）" for r in top_rules],
        "暂无显著关联",
    )
    fallback = (
        f"{prompts.DEGRADED_NOTICE}\n"
        f"降级原因：{reason}\n\n"
        f"【经营概况】{period} 期间覆盖 {sku_count} 个 SKU，销售额合计 "
        f"{_num(total_sales)} 元，其中 A 类核心商品 {a_count} 个。\n\n"
        f"【补货提醒】{len(urgent)} 个商品已低于补货点：\n{urgent_text}\n\n"
        f"【滞销商品】{slow_text}\n\n"
        f"【关联陈列】提升度最高的组合：{relation_text}。建议把强关联商品摆在相邻位置。\n"
    )
    return fallback, False


def analyze_slow_movers(profiles: list, days: int = 90) -> tuple[list[dict], bool]:
    """L2 滞销归因。返回 (分析结果列表, 是否为真实模型输出)。"""
    slow = _slow_profiles(profiles)
    if not slow:
        return [], True

    lines = []
    for p in slow[:15]:
        lines.append(
            f"- {p.sku_id} {p.sku_name or ''}：日均销量 {_num(p.mean_sales, 3)}，"
            f"CV {_num(p.cv, 3)}，现有库存参考周转天数 {_num(p.turnover_days, 1)} 天，"
            f"ABC={p.abc_class}，XYZ={p.xyz_class}"
        )
    user_prompt = prompts.SLOW_MOVER_USER.format(days=days, slow_list="\n".join(lines))

    client = get_client()
    try:
        parsed = client.chat_json(prompts.SLOW_MOVER_SYSTEM, user_prompt)
    except LLMUnavailable:
        return [], False
    except Exception:
        return [], False

    if isinstance(parsed, dict):
        for key in ("items", "data", "results", "慢销商品"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            parsed = [parsed]
    if not isinstance(parsed, list):
        return [], False

    known = {p.sku_id for p in slow}
    cleaned: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        sku = str(item.get("sku_id", "")).strip()
        if sku not in known:
            continue
        cleaned.append(
            {
                "sku_id": sku,
                "reason": str(item.get("reason", "未说明"))[:120],
                "action": str(item.get("action", "未说明"))[:120],
                "note": str(item.get("note", ""))[:200],
            }
        )
    return cleaned, bool(cleaned)


def suggest_layout(rules: list, top_n: int = 10) -> tuple[str, bool]:
    """L3 陈列布局建议。返回 (建议文本, 是否为真实模型输出)。"""
    positive = sorted(
        [r for r in (rules or []) if getattr(r, "lift", 0) > 1],
        key=lambda r: getattr(r, "lift", 0),
        reverse=True,
    )[: max(1, top_n)]

    if not positive:
        return (
            "暂无可用的正向连带关系。请先导入足够的小票数据，"
            "并在「参数配置」里适当降低最小支持度后重试。",
            True,
        )

    association_list = "\n".join(
        f"- {r.antecedent} + {r.consequent}：支持度 {r.support:.3f}，"
        f"置信度 {r.confidence:.3f}，提升度 {r.lift:.3f}"
        for r in positive
    )
    user_prompt = prompts.LAYOUT_USER.format(association_list=association_list)

    client = get_client()
    try:
        text = client.chat(prompts.LAYOUT_SYSTEM, user_prompt)
        return text.strip(), True
    except LLMUnavailable:
        pass
    except Exception:
        pass

    lines = [
        prompts.DEGRADED_NOTICE,
        "",
        "【规则版陈列建议】以下组合的提升度明显大于 1，建议放在相邻货架或同一端架：",
    ]
    for r in positive[:5]:
        lines.append(
            f"- {r.antecedent} 与 {r.consequent}（lift {r.lift:.2f}）："
            "把高单价 / 高毛利商品放在靠里侧，带动另一件商品经过。"
        )
    lines.append("以上为统计规则输出，未经过大模型润色。")
    return "\n".join(lines), False


def recommend_seasonal(
    records: list, current_month: int, categories: list[str]
) -> tuple[str, bool]:
    """L4 换季商品推荐。返回 (推荐文本, 是否为真实模型输出)。

    判断由 app.core.seasonal 完成，模型只负责把结论组织成人话。
    """
    from app.core import seasonal

    recs = seasonal.recommend(records or [], current_month)
    categories = [str(c) for c in (categories or []) if str(c).strip()]
    category_text = "、".join(categories) if categories else "未提供商品品类"

    if not recs:
        return (
            "当前销售数据不足，无法判断换季趋势。"
            "请至少导入 2~3 个月的小票数据后重试。",
            True,
        )

    trend_lines = "\n".join(
        f"- {r.get('sku_name') or r['sku_id']}：{r['reason']}；建议：{r['action']}"
        for r in recs[:10]
    )
    user_prompt = prompts.SEASONAL_USER.format(
        month=current_month,
        categories=category_text,
        trend_lines=trend_lines,
    )

    client = get_client()
    try:
        text = client.chat(prompts.SEASONAL_SYSTEM, user_prompt)
        return text.strip(), True
    except LLMUnavailable:
        pass
    except Exception:
        pass

    lines = [prompts.DEGRADED_NOTICE, "", "【规则版换季建议】"]
    for r in recs[:5]:
        lines.append(
            f"- {r.get('sku_name') or r['sku_id']}：{r['reason']}；建议{r['action']}。"
        )
    return "\n".join(lines), False


def map_trend_to_sku(trend_text: str, categories: list[str]) -> tuple[list[dict], bool]:
    """L5 网络热点 → 品类映射。返回 (建议列表, 是否为真实模型输出)。

    这个模块最需要降级：外部接口可能失败，模型也可能失败，两层都要扛住。
    """
    trend_text = str(trend_text or "").strip()
    categories = [str(c) for c in (categories or []) if str(c).strip()]
    if not trend_text:
        return [], False

    # 先截断，别把几万字的热点原文塞给 4B 模型
    trend_text = trend_text[:2000]
    user_prompt = prompts.TREND_USER.format(
        trend_text=trend_text,
        categories="、".join(categories) if categories else "未提供",
        customer_profile="社区新零售小店的日常客群，以周边居民为主",
    )

    client = get_client()
    try:
        parsed = client.chat_json(prompts.TREND_SYSTEM, user_prompt)
    except LLMUnavailable:
        return _keyword_fallback(trend_text, categories), False
    except Exception:
        return _keyword_fallback(trend_text, categories), False

    if isinstance(parsed, dict):
        for key in ("items", "data", "results", "trends"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            parsed = [parsed]
    if not isinstance(parsed, list):
        return _keyword_fallback(trend_text, categories), False

    cleaned: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        keyword = str(item.get("keyword", "")).strip()
        category = str(item.get("category", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if not keyword or not category:
            continue
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        cleaned.append(
            {
                "keyword": keyword[:60],
                "category": category[:60],
                "reason": reason[:200],
                "confidence": round(max(0.0, min(1.0, confidence)), 2),
            }
        )
    if cleaned:
        return cleaned, True
    return _keyword_fallback(trend_text, categories), False


def _keyword_fallback(trend_text: str, categories: list[str]) -> list[dict]:
    """模型不可用时的规则兜底：品类名直接出现在热点原文里就算命中。"""
    results = []
    for category in categories:
        if category and category in trend_text:
            results.append(
                {
                    "keyword": category,
                    "category": category,
                    "reason": "热点原文中出现了该品类关键词（规则匹配，未经模型判断）",
                    "confidence": 0.3,
                }
            )
    return results


def explain_anomaly(context: dict) -> str:
    """L6 异常归因：销量突变、库存异常等情况用自然语言解释。

    输入是算法层算好的统计量 dict，输出一段解释文本。
    模型不可用时返回一句简短的客观描述。
    """
    context = context or {}
    if not context:
        return "暂无足够数据生成异常说明，建议补充更多销售记录后重试。"

    lines = [f"- {key}：{value}" for key, value in context.items()]
    user_prompt = "以下是一组经营异常指标，请用 2~3 句话解释可能原因并给出处理建议：\n" + "\n".join(
        lines
    )
    client = get_client()
    try:
        return client.chat(prompts.BASE_SYSTEM, user_prompt).strip()
    except LLMUnavailable:
        pass
    except Exception:
        pass

    summary = "；".join(f"{key} 为 {value}" for key, value in list(context.items())[:5])
    return (
        f"基础统计模式：{summary}。"
        "该异常超过当前阈值，建议核对库存与近期促销活动；"
        "本地模型不可用，暂无法生成更详细的归因分析。"
    )


def health_check() -> tuple[bool, str]:
    """检查模型可用性，返回 (是否可用, 提示文案)。前端页面顶部用它显示状态。"""
    client = get_client()
    if not client.is_available():
        return False, "模型服务未启动，智能分析功能已降级"
    models = client.list_models()
    wanted = client.config.model
    if not models:
        return False, "Ollama 已启动，但一个模型都没有安装（ollama pull qwen3:4b）"
    if wanted not in models and not any(
        m.split(":")[0] == wanted.split(":")[0] for m in models
    ):
        return (
            False,
            f"Ollama 已启动，但未安装模型 {wanted}（已安装：{'、'.join(models)}）；"
            "智能分析将降级为基础统计模式",
        )
    return True, f"模型服务正常　已安装：{', '.join(models)}"
