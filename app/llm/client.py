"""【M7】大模型客户端 —— 支持 Ollama 本地模型与第三方 OpenAI 兼容 API。

默认走 Ollama，数据不出本机。用户在「参数配置」里显式选择第三方 API 后，
才会把**聚合后的统计摘要**发送到服务商；原始 CSV、数据库文件不会上传。
第三方 API 适配的是 OpenAI Chat Completions 协议，可接 DeepSeek、通义千问
兼容模式、OpenAI、Moonshot 等服务。

对应需求：2.2.3 模型调用一般性规定（默认本地，第三方为显式可选）
对应需求：2.2.4 异常处理一般性规定
    "当...本地LLM调用失败时，系统不应直接崩溃，应给出明确报错提示，
     对应推荐模块降级停用，其余库存、补货分析功能仍可正常运行"

------------------------------------------------------------
本机实测性能（2026-10-13，qwen3:4b，纯 CPU 推理，8核 Ryzen）
------------------------------------------------------------
    生成速度    约 16~18 tokens/秒
    首次调用    约 16 秒（含模型载入内存的 2.5 GB）

    ⚠ 最重要的实测结论：qwen3 默认会先"思考"再回答，思考过程
      动辄 1000+ tokens，把一次简单调用拖到 60~116 秒，而且
      think=False 和 /no_think 软开关在本机都拦不住它。

      实测对比（同一个滞销归因任务）：
        裸调用                  116.1 秒   输出 1760 tok   JSON 非法
        format=json + 限300tok    5.1 秒   输出   88 tok   JSON 合法

      结论：**所有结构化输出必须走 format="json" 并限制 num_predict**，
      这不只是"规范"，是本项目能不能在超时时间内出结果的生死线。

------------------------------------------------------------
Ollama 接口速查
------------------------------------------------------------
    服务地址：http://127.0.0.1:11434
    对话接口：POST http://127.0.0.1:11434/api/chat        （Ollama 原生）
              POST http://127.0.0.1:11434/v1/chat/completions（OpenAI 兼容）

    请求体（推荐用原生接口，因为要传 format 和 options）：
        {
          "model": "qwen3:4b",
          "messages": [
            {"role": "system", "content": "你是一名零售经营分析师……"},
            {"role": "user",   "content": "以下是本周数据摘要：……"}
          ],
          "stream": false,
          "format": "json",                  ← 结构化输出必加
          "options": {"num_predict": 300,    ← 限制输出长度，给耗时上保险
                      "temperature": 0.3}
        }

    响应体（原生接口只取关心字段）：
        {"message": {"content": "模型的回答"},
         "eval_count": 88,          ← 生成的 token 数
         "eval_duration": 4890000000 ← 生成耗时（纳秒），可算真实吞吐}

    健康检查：GET http://127.0.0.1:11434/api/tags
              能返回 200 就说明服务活着
------------------------------------------------------------
"""


from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import requests

OLLAMA_BASE = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3:4b"

# 需求 2.4.2：外部接口超时设置。模型推理慢，给的时间比热点接口（8s）长
CHAT_TIMEOUT = 60
HEALTH_TIMEOUT = 3

PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"

PROVIDER_LABELS = {
    PROVIDER_OLLAMA: "Ollama 本地模型",
    PROVIDER_OPENAI: "第三方 OpenAI 兼容 API",
}


class LLMUnavailable(RuntimeError):
    """模型不可用时抛出，调用方捕获后走降级逻辑。"""


@dataclass
class LLMConfig:
    # 本地 Ollama
    model: str = DEFAULT_MODEL
    temperature: float = 0.3
    timeout: int = CHAT_TIMEOUT
    base_url: str = OLLAMA_BASE

    # 第三方 OpenAI 兼容 API
    provider: str = PROVIDER_OLLAMA
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""
    api_timeout: int = CHAT_TIMEOUT


class LLMClient:
    """模型客户端：默认 Ollama，也可切到第三方 OpenAI 兼容 API。

    两条路径共用 chat() / chat_json()，上层任务不需要关心是本地还是远程。
    """

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        if self.config.provider not in PROVIDER_LABELS:
            self.config.provider = PROVIDER_OLLAMA
        self.last_error: str | None = None

    # ==========================================================
    # 通用属性
    # ==========================================================
    @property
    def provider(self) -> str:
        return self.config.provider

    @property
    def provider_label(self) -> str:
        return PROVIDER_LABELS.get(self.provider, "模型")

    @property
    def is_remote(self) -> bool:
        return self.provider == PROVIDER_OPENAI

    @property
    def request_timeout(self) -> int:
        return self._api_timeout() if self.is_remote else int(self.config.timeout)

    def _api_key(self) -> str:
        # 环境变量优先，适合不想把 Key 写进 SQLite 的用户
        return (os.environ.get("SMARTWMS_API_KEY") or self.config.api_key or "").strip()

    def _api_base(self) -> str:
        return (self.config.api_base_url or "").strip().rstrip("/")

    def _api_model(self) -> str:
        return (self.config.api_model or "").strip()

    def _api_timeout(self) -> int:
        try:
            return max(5, int(self.config.api_timeout))
        except (TypeError, ValueError):
            return CHAT_TIMEOUT

    # ==========================================================
    # 探测 / 基础信息
    # ==========================================================
    def is_available(self) -> bool:
        """检查当前模型来源是否可用。探测失败返回 False，绝不抛异常。"""
        if self.is_remote:
            return self._remote_available()
        try:
            resp = requests.get(
                f"{self.config.base_url}/api/tags",
                timeout=HEALTH_TIMEOUT,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def list_models(self) -> list[str]:
        """列出可用模型：本地是 Ollama 已下载模型，远程是 /models 返回的 id。"""
        if self.is_remote:
            return self._remote_models()
        try:
            resp = requests.get(
                f"{self.config.base_url}/api/tags", timeout=HEALTH_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return []

    # ==========================================================
    # 第三方 OpenAI 兼容 API
    # ==========================================================
    def _remote_chat_url(self) -> str:
        base = self._api_base()
        if not base:
            return ""
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _remote_models_url(self) -> str:
        base = self._api_base()
        if not base:
            return ""
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        if base.endswith("/v1"):
            return f"{base}/models"
        return f"{base}/v1/models"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

    def _remote_available(self) -> bool:
        if not self._api_base() or not self._api_model():
            self.last_error = "config"
            return False
        if not self._api_key():
            self.last_error = "config"
            return False
        try:
            resp = requests.get(
                self._remote_models_url(),
                headers=self._auth_headers(),
                timeout=min(HEALTH_TIMEOUT, self._api_timeout()),
            )
        except requests.RequestException:
            self.last_error = "connection"
            return False

        if resp.status_code == 200:
            return True
        if resp.status_code in (401, 403):
            self.last_error = "auth"
            return False
        if resp.status_code == 404:
            # 有些兼容接口不实现 /models，不能据此判定不可用；
            # 真正调用 chat 时再校验。
            self.last_error = "models_unsupported"
            return True
        self.last_error = f"http_{resp.status_code}"
        return False

    def _remote_models(self) -> list[str]:
        if not self._api_base() or not self._api_key():
            return []
        try:
            resp = requests.get(
                self._remote_models_url(),
                headers=self._auth_headers(),
                timeout=min(HEALTH_TIMEOUT, self._api_timeout()),
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            items = data.get("data", []) if isinstance(data, dict) else []
            return [str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")]
        except (requests.RequestException, ValueError, TypeError):
            return []

    def _post_openai(self, payload: dict, json_mode: bool = False) -> str:
        url = self._remote_chat_url()
        if not url:
            self.last_error = "config"
            raise LLMUnavailable("未配置第三方 API 地址")
        if not self._api_key():
            self.last_error = "config"
            raise LLMUnavailable("未配置第三方 API Key")

        body = dict(payload)
        try:
            for attempt in range(2):
                try:
                    resp = requests.post(
                        url,
                        json=body,
                        headers=self._auth_headers(),
                        timeout=self._api_timeout(),
                    )
                except requests.Timeout as exc:
                    self.last_error = "timeout"
                    raise LLMUnavailable(
                        f"第三方 API 响应超时（>{self._api_timeout()} 秒）"
                    ) from exc
                except requests.ConnectionError as exc:
                    self.last_error = "connection"
                    raise LLMUnavailable("无法连接第三方 API，请检查 Base URL 和网络") from exc
                except requests.RequestException as exc:
                    self.last_error = "request"
                    raise LLMUnavailable(f"调用第三方 API 失败：{exc}") from exc

                # 个别兼容接口不认 response_format，去掉后重试一次
                if (
                    attempt == 0
                    and json_mode
                    and "response_format" in body
                    and resp.status_code in (400, 422)
                ):
                    body.pop("response_format", None)
                    continue

                if resp.status_code >= 400:
                    if resp.status_code in (401, 403):
                        self.last_error = "auth"
                        raise LLMUnavailable("第三方 API 鉴权失败（401/403），请检查 API Key")
                    if resp.status_code == 429:
                        self.last_error = "rate_limit"
                        raise LLMUnavailable("第三方 API 触发限流（429），请稍后重试")
                    if resp.status_code == 404:
                        self.last_error = "not_found"
                        raise LLMUnavailable(
                            "第三方 API 地址或模型不存在（404），请检查 Base URL / 模型名"
                        )
                    self.last_error = f"http_{resp.status_code}"
                    detail = self._error_detail(resp)
                    raise LLMUnavailable(f"第三方 API 返回 HTTP {resp.status_code}：{detail}")
                break
            else:
                self.last_error = "request"
                raise LLMUnavailable("第三方 API 拒绝了 JSON 输出格式，请更换模型或关闭 JSON 模式")
        except LLMUnavailable:
            raise

        try:
            data = resp.json()
        except ValueError as exc:
            self.last_error = "bad_response"
            raise LLMUnavailable("第三方 API 返回了非 JSON 响应") from exc

        try:
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content", "")
            if isinstance(content, list):
                content = "".join(
                    str(part.get("text", "")) for part in content if isinstance(part, dict)
                )
        except (KeyError, IndexError, TypeError) as exc:
            self.last_error = "bad_response"
            raise LLMUnavailable("第三方 API 返回结构不符合 OpenAI 兼容格式") from exc

        text = str(content or "").strip()
        if not text:
            self.last_error = "empty"
            raise LLMUnavailable("第三方 API 返回了空内容")
        return text

    @staticmethod
    def _error_detail(resp: requests.Response) -> str:
        """提取第三方 API 的错误信息，截断后用于界面展示。"""
        try:
            data = resp.json()
            if isinstance(data, dict):
                error = data.get("error")
                if isinstance(error, dict):
                    message = error.get("message") or error.get("code") or ""
                else:
                    message = str(error or data.get("message", ""))
                if message:
                    return str(message)[:180]
        except ValueError:
            pass
        return (resp.text or "无错误详情")[:180]

    # ==========================================================
    # 本地 Ollama
    # ==========================================================
    def _post_ollama(self, payload: dict) -> str:
        """POST /api/chat，返回模型回答文本；所有异常转成 LLMUnavailable。"""
        url = f"{self.config.base_url}/api/chat"
        try:
            resp = requests.post(url, json=payload, timeout=self.config.timeout)
            resp.raise_for_status()
        except requests.Timeout as exc:
            self.last_error = "timeout"
            raise LLMUnavailable(
                f"本地模型响应超时（>{self.config.timeout} 秒）"
            ) from exc
        except requests.ConnectionError as exc:
            self.last_error = "connection"
            raise LLMUnavailable("无法连接本地模型服务，请确认 Ollama 已启动") from exc
        except requests.RequestException as exc:
            self.last_error = "request"
            raise LLMUnavailable(f"调用本地模型失败：{exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            self.last_error = "bad_response"
            raise LLMUnavailable("本地模型返回了非 JSON 响应") from exc

        try:
            if isinstance(data.get("message"), dict):
                content = data["message"].get("content", "")
            elif data.get("choices"):
                content = data["choices"][0]["message"]["content"]
            elif "response" in data:
                content = data["response"]
            else:
                content = ""
        except (KeyError, IndexError, TypeError) as exc:
            self.last_error = "bad_response"
            raise LLMUnavailable("本地模型返回结构不符合预期") from exc

        text = str(content or "").strip()
        if not text:
            self.last_error = "empty"
            raise LLMUnavailable("本地模型返回了空内容")
        return text

    # ==========================================================
    # 统一对话入口
    # ==========================================================
    def _request(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
        max_tokens: int = 800,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if self.is_remote:
            payload = {
                "model": self._api_model(),
                "messages": messages,
                "temperature": self.config.temperature,
                "stream": False,
                "max_tokens": max_tokens,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            return self._post_openai(payload, json_mode=json_mode)

        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"
        return self._post_ollama(payload)

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """发一次对话请求，返回模型输出的纯文本。"""
        return self._request(system_prompt, user_prompt, json_mode=False, max_tokens=800)

    def chat_json(
        self, system_prompt: str, user_prompt: str, retries: int = 1
    ) -> dict | list:
        """要求模型返回 JSON，并校验解析结果。

        本地 Ollama 走 format="json"；第三方 API 走 response_format，
        如果服务商不支持则自动去掉该字段重试一次。
        """
        attempts = max(0, int(retries)) + 1
        last_problem = "模型没有返回可解析的 JSON"

        for attempt in range(attempts):
            prompt = user_prompt + (
                "\n\n注意：上一次输出不是合法 JSON。"
                "这次只输出一个 JSON 对象，不要任何解释文字。"
                if attempt
                else ""
            )
            try:
                text = self._request(
                    system_prompt,
                    prompt,
                    json_mode=True,
                    max_tokens=400,
                )
            except LLMUnavailable as exc:
                # 网络 / 超时 / 鉴权 / 限流类错误重试没有意义，直接抛给上层
                if self.last_error in {
                    "connection",
                    "timeout",
                    "auth",
                    "rate_limit",
                    "config",
                    "not_found",
                }:
                    raise
                last_problem = str(exc)
                continue

            parsed = _extract_json(text)
            if isinstance(parsed, (dict, list)):
                return parsed
            last_problem = "模型输出无法解析为 JSON"

        self.last_error = "json"
        raise LLMUnavailable(last_problem)

    # ==========================================================
    # 降级文案
    # ==========================================================
    def degrade_reason(self) -> str:
        """模型不可用时，给用户看的提示文案。"""
        if self.is_remote:
            return self._remote_degrade_reason()

        if not self.is_available():
            return (
                f"本地模型服务未启动（{self.config.base_url} 无响应），"
                "已切换为基础统计模式。库存与补货计算不受影响，智能推荐功能暂不可用。"
            )

        models = self.list_models()
        wanted = self.config.model
        if models and wanted not in models and not any(
            m.split(":")[0] == wanted.split(":")[0] for m in models
        ):
            installed = "、".join(models) if models else "无"
            return (
                f"Ollama 服务正常，但未找到模型 {wanted}（已安装：{installed}）。"
                "已切换为基础统计模式；执行 ollama pull "
                f"{wanted} 后即可恢复智能分析。"
            )

        if self.last_error == "timeout":
            return (
                f"本地模型响应超时（>{self.config.timeout} 秒），"
                "已切换为基础统计模式。可以尝试更小的模型档位，或缩短分析窗口。"
            )
        if self.last_error == "json":
            return (
                "本地模型连续返回了不合法的 JSON，已切换为基础统计模式。"
                "这通常是模型档位太小导致的，建议换用 qwen3:4b 或更大的模型。"
            )
        if self.last_error in {"connection", "request"}:
            return (
                "本地模型服务连接中断，已切换为基础统计模式。"
                "请检查 Ollama 是否仍在运行。"
            )
        return (
            "本地模型调用失败，已切换为基础统计模式。"
            "所有统计与算法结果仍可正常使用，智能文字解读暂不可用。"
        )

    def _remote_degrade_reason(self) -> str:
        if not self._api_base() or not self._api_model():
            return (
                "第三方 API 配置不完整（Base URL / 模型名），已切换为基础统计模式。"
                "请到「参数配置」页填写接口地址和模型名。"
            )
        if not self._api_key():
            return (
                "第三方 API 未配置 API Key，已切换为基础统计模式。"
                "请在「参数配置」页填写，或设置环境变量 SMARTWMS_API_KEY。"
            )
        if self.last_error == "auth":
            return (
                "第三方 API 鉴权失败（401/403），已切换为基础统计模式。"
                "请检查 API Key 是否有效、是否有该模型权限。"
            )
        if self.last_error == "rate_limit":
            return (
                "第三方 API 触发限流（429），已切换为基础统计模式。"
                "请稍后重试，或检查账户余额 / 配额。"
            )
        if self.last_error == "timeout":
            return (
                f"第三方 API 响应超时（>{self._api_timeout()} 秒），已切换为基础统计模式。"
                "可以调大超时时间或换更快的模型。"
            )
        if self.last_error == "connection":
            return (
                "无法连接第三方 API，已切换为基础统计模式。"
                "请检查 Base URL、网络或代理设置。"
            )
        if self.last_error == "not_found":
            return (
                "第三方 API 地址或模型名不存在（404），已切换为基础统计模式。"
                "请检查 Base URL 是否包含 /v1，以及模型名是否正确。"
            )
        if self.last_error == "json":
            return (
                "第三方 API 连续返回不合法 JSON，已切换为基础统计模式。"
                "可以更换支持 JSON 输出的模型，或检查接口兼容性。"
            )
        if self.last_error == "models_unsupported":
            return (
                "第三方 API 已配置，但该服务不提供 /models 探测接口；"
                "实际生成报告时会直接调用 /chat/completions。"
            )
        return (
            "第三方 API 调用失败，已切换为基础统计模式。"
            "所有统计与算法结果仍可正常使用，智能文字解读暂不可用。"
        )


_FENCE_PATTERN = re.compile(r"```(?:json|JSON)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> dict | list | None:
    """从模型输出里尽量提取一个 JSON 对象/数组。"""
    if not text:
        return None
    cleaned = text.strip()

    fence = _FENCE_PATTERN.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    candidates = [
        (cleaned.find("{"), "{", "}"),
        (cleaned.find("["), "[", "]"),
    ]
    candidates = sorted((item for item in candidates if item[0] >= 0), key=lambda item: item[0])

    for start, opener, closer in candidates:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(cleaned)):
            char = cleaned[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : index + 1])
                    except json.JSONDecodeError:
                        break
    return None


def client_from_config(config: dict) -> LLMClient:
    """根据 config 表构造客户端。"""
    provider = str(config.get("llm_provider", PROVIDER_OLLAMA)).strip().lower()
    if provider not in PROVIDER_LABELS:
        provider = PROVIDER_OLLAMA

    def _int(value, default: int) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    return LLMClient(
        LLMConfig(
            model=str(config.get("model", DEFAULT_MODEL) or DEFAULT_MODEL),
            base_url=str(config.get("ollama_base_url", OLLAMA_BASE) or OLLAMA_BASE),
            provider=provider,
            api_base_url=os.environ.get("SMARTWMS_API_BASE")
            or str(config.get("api_base_url", "") or ""),
            api_key=os.environ.get("SMARTWMS_API_KEY")
            or str(config.get("api_key", "") or ""),
            api_model=os.environ.get("SMARTWMS_API_MODEL")
            or str(config.get("api_model", "") or ""),
            api_timeout=_int(config.get("api_timeout", CHAT_TIMEOUT), CHAT_TIMEOUT),
        )
    )


def apply_config(config: dict | None = None) -> LLMClient:
    """把数据库配置应用到全局客户端。"""
    global _client
    if config is None:
        from app.db import schema

        config = schema.get_config()
    _client = client_from_config(config)
    return _client


def get_client() -> LLMClient:
    """获取全局唯一的客户端实例。"""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


_client: LLMClient | None = None
