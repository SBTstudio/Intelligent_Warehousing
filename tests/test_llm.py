"""本地大模型客户端与任务降级测试（M7 / M8）。

不依赖真实 Ollama：把 base_url 指向一个不存在的端口，验证：
    · 网络失败时抛 LLMUnavailable，而不是让界面崩溃
    · degrade_reason 能区分"服务未启动"
    · chat_json 能剥掉 ```json 包裹并解析
    · 六个任务函数在模型不可用时返回模板兜底（第二个返回值为 False）
"""

from __future__ import annotations

import json

import pytest

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


# =====================================================================
# 第三方 OpenAI 兼容 API
# =====================================================================
class _FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {}, ensure_ascii=False)

    def json(self):
        return self._payload


def _remote_client(**kwargs) -> llm_client.LLMClient:
    config = llm_client.LLMConfig(
        provider=llm_client.PROVIDER_OPENAI,
        api_base_url="https://api.example.com/v1",
        api_key="sk-test",
        api_model="test-model",
        api_timeout=20,
    )
    for key, value in kwargs.items():
        setattr(config, key, value)
    return llm_client.LLMClient(config)


def test_remote_chat_uses_openai_protocol(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return _FakeResponse(200, {"choices": [{"message": {"content": "你好，店主"}}]})

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    client = _remote_client()
    assert client.chat("system", "user") == "你好，店主"

    assert calls[0]["url"] == "https://api.example.com/v1/chat/completions"
    assert calls[0]["json"]["model"] == "test-model"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert calls[0]["json"]["messages"][0]["role"] == "system"


def test_remote_chat_json_uses_response_format(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return _FakeResponse(
            200,
            {"choices": [{"message": {"content": '```json\n{"ok": true}\n```'}}]},
        )

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    parsed = _remote_client().chat_json("system", "user")
    assert parsed == {"ok": True}
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_remote_json_falls_back_without_response_format(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(dict(json or {}))
        if len(calls) == 1:
            return _FakeResponse(400, {"error": {"message": "response_format unsupported"}})
        return _FakeResponse(200, {"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    assert _remote_client().chat_json("system", "user") == {"ok": True}
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


def test_remote_missing_key_degrades(monkeypatch):
    monkeypatch.delenv("SMARTWMS_API_KEY", raising=False)
    client = _remote_client(api_key="")
    with pytest.raises(llm_client.LLMUnavailable):
        client.chat("system", "user")
    assert "API Key" in client.degrade_reason()


def test_remote_auth_failure_is_reported(monkeypatch):
    monkeypatch.setattr(
        llm_client.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse(401, {"message": "bad token"}),
    )
    client = _remote_client()
    assert client.is_available() is False
    assert "鉴权失败" in client.degrade_reason()


def test_remote_is_available_and_lists_models(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return _FakeResponse(
            200, {"data": [{"id": "test-model"}, {"id": "other-model"}]}
        )

    monkeypatch.setattr(llm_client.requests, "get", fake_get)
    client = _remote_client()
    assert client.is_available() is True
    assert client.list_models() == ["test-model", "other-model"]
    assert calls[0] == "https://api.example.com/v1/models"


def test_client_from_config_reads_provider_fields(monkeypatch):
    monkeypatch.delenv("SMARTWMS_API_KEY", raising=False)
    client = llm_client.client_from_config(
        {
            "llm_provider": "openai",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-config",
            "api_model": "deepseek-chat",
            "api_timeout": "45",
        }
    )
    assert client.provider == llm_client.PROVIDER_OPENAI
    assert client.config.api_model == "deepseek-chat"
    assert client.config.api_timeout == 45
    assert client.is_remote is True


def test_env_api_key_overrides_config(monkeypatch):
    monkeypatch.setenv("SMARTWMS_API_KEY", "sk-env")
    client = _remote_client(api_key="sk-config")
    assert client._api_key() == "sk-env"
