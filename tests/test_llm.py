"""本地大模型客户端与任务降级测试（M7 / M8）。

不依赖真实 Ollama：把 base_url 指向一个不存在的端口，验证：
    · 网络失败时抛 LLMUnavailable，而不是让界面崩溃
    · degrade_reason 能区分"服务未启动"
    · chat_json 能剥掉 ```json 包裹并解析
    · 六个任务函数在模型不可用时返回模板兜底（第二个返回值为 False）
"""

from __future__ import annotations

from app.core import basket, classify, ingest, replenish
from app.llm import client as llm_client
from app.llm import prompts, tasks


def _unavailable_client() -> llm_client.LLMClient:
    return llm_client.LLMClient(
        llm_client.LLMConfig(
            base_url="http://127.0.0.1:59999",
            timeout=1,
        )
    )


def test_is_available_false_when_port_closed():
    assert _unavailable_client().is_available() is False


def test_chat_raises_llm_unavailable():
    client = _unavailable_client()
    try:
        client.chat("system", "user")
    except llm_client.LLMUnavailable as exc:
        assert "无法连接" in str(exc)
    else:
        raise AssertionError("服务不可用时 chat() 应抛 LLMUnavailable")


def test_degrade_reason_mentions_service():
    reason = _unavailable_client().degrade_reason()
    assert "未启动" in reason
    assert "基础统计模式" in reason


def test_extract_json_handles_code_fence():
    parsed = llm_client._extract_json(
        '好的，结果如下：\n```json\n{"sku_id": "S1", "reason": "季节性衰退"}\n```'
    )
    assert parsed == {"sku_id": "S1", "reason": "季节性衰退"}


def test_extract_json_handles_surrounding_text():
    parsed = llm_client._extract_json(
        '这是结果 [{"keyword": "低糖", "category": "饮料", "confidence": 0.8}] 请查收'
    )
    assert isinstance(parsed, list)
    assert parsed[0]["category"] == "饮料"


def test_generate_report_falls_back(monkeypatch):
    client = _unavailable_client()
    monkeypatch.setattr(tasks, "get_client", lambda: client)
    records, inventory = ingest.load_sample()
    profiles = classify.analyze(records, inventory)
    suggestions = replenish.build_all_suggestions(records, inventory)
    rules = basket.mine_rules(basket.build_baskets(records), 0.01, 0.3)

    text, used = tasks.generate_report(
        suggestions, profiles, rules, period="本周", sample_size=len(records)
    )
    assert used is False
    assert "基础统计模式" in text
    assert "经营概况" in text
    assert "补货提醒" in text


def test_suggest_layout_falls_back(monkeypatch):
    client = _unavailable_client()
    monkeypatch.setattr(tasks, "get_client", lambda: client)
    records, _ = ingest.load_sample()
    rules = basket.mine_rules(basket.build_baskets(records), 0.01, 0.3)
    text, used = tasks.suggest_layout(rules)
    assert used is False
    assert "基础统计模式" in text
    assert "陈列" in text


def test_map_trend_falls_back_to_keyword_match(monkeypatch):
    client = _unavailable_client()
    monkeypatch.setattr(tasks, "get_client", lambda: client)
    items, used = tasks.map_trend_to_sku("最近低糖饮料很受欢迎", ["饮料", "零食"])
    assert used is False
    assert items and items[0]["category"] == "饮料"


def test_health_check_without_service(monkeypatch):
    client = _unavailable_client()
    monkeypatch.setattr(tasks, "get_client", lambda: client)
    available, message = tasks.health_check()
    assert available is False
    assert "未启动" in message


def test_explain_anomaly_without_service(monkeypatch):
    client = _unavailable_client()
    monkeypatch.setattr(tasks, "get_client", lambda: client)
    text = tasks.explain_anomaly({"销量变化": "-40%", "库存": 12})
    assert "基础统计模式" in text
    assert "销量变化" in text


def test_prompt_templates_have_required_fields():
    # 防止改 Prompt 时把占位符写丢，format 会抛 KeyError
    prompts.REPORT_USER.format(
        period="本周",
        analysis_time="2026-01-01",
        sample_size=1,
        sku_count=1,
        urgent_count=0,
        replenish_lines="",
        best_sellers="",
        slow_count=0,
        slow_movers="",
        association_lines="",
    )
    prompts.SLOW_MOVER_USER.format(days=90, slow_list="")
    prompts.TREND_USER.format(trend_text="", categories="", customer_profile="")
