"""DeepSeek 客户端：多模型路由 + 超时重试 + token 成本统计 + 流式输出。"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """模型调用失败（已重试）。"""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    cost: float = 0.0
    estimated: bool = False

    def to_dict(self) -> dict:
        return {
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "reasoningTokens": self.reasoning_tokens,
            "totalTokens": self.total_tokens,
            "model": self.model,
            "cost": round(self.cost, 6),
            "estimated": self.estimated,
        }


@dataclass
class LLMResponse:
    content: str
    reasoning: str = ""
    usage: Usage = field(default_factory=Usage)
    tool_calls: list = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    """粗略估算 token：中文按 0.6 token/字，英文按 0.3 token/字符。"""
    if not text:
        return 0
    chinese = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - chinese
    return max(1, int(chinese * 0.6 + other * 0.3))


class DeepSeekClient:
    """DeepSeek OpenAI 兼容接口封装。

    - 简单任务（摘要、问答）走 fast 模型
    - 复杂任务（今日要闻、深度分析）走 pro 模型
    """

    TASK_MODEL = {
        "chat": "fast",
        "summary": "fast",
        "related": "fast",
        "digest": "pro",
        "analysis": "pro",
    }

    def __init__(self) -> None:
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.api_key = settings.deepseek_api_key
        self.timeout = settings.llm_timeout
        self.max_retries = settings.llm_max_retries

    # ---------- 路由与计费 ----------
    def model_for(self, task: str) -> str:
        tier = self.TASK_MODEL.get(task, "fast")
        return settings.deepseek_model_pro if tier == "pro" else settings.deepseek_model_fast

    def price_for(self, model: str) -> tuple[float, float]:
        if model == settings.deepseek_model_pro:
            return settings.price_in_pro, settings.price_out_pro
        return settings.price_in_fast, settings.price_out_fast

    def build_usage(self, model: str, prompt_tokens: int, completion_tokens: int,
                    reasoning_tokens: int = 0, estimated: bool = False) -> Usage:
        price_in, price_out = self.price_for(model)
        cost = prompt_tokens / 1_000_000 * price_in + completion_tokens / 1_000_000 * price_out
        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model=model,
            cost=cost,
            estimated=estimated,
        )

    # ---------- HTTP ----------
    def _payload(self, messages: list[dict], model: str, temperature: float,
                 max_tokens: Optional[int], json_mode: bool) -> dict:
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if settings.llm_send_effort:
            payload["reasoning_effort"] = settings.llm_effort
        return payload

    async def _request(self, payload: dict) -> dict:
        if not self.api_key:
            raise LLMError("未配置 DEEPSEEK_API_KEY，请检查 .env")

        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise LLMError(f"模型服务暂时不可用（{resp.status_code}）：{resp.text[:200]}")
                raise LLMError(f"模型调用失败（{resp.status_code}）：{resp.text[:300]}")
            except (httpx.TimeoutException, httpx.NetworkError, LLMError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                wait = 1.5 * (attempt + 1)
                logger.warning("LLM 调用失败，%ss 后重试（%s/%s）：%s", wait, attempt + 1,
                               self.max_retries, exc)
                await asyncio.sleep(wait)
        raise LLMError(f"模型调用失败：{last_error}")

    # ---------- 非流式 ----------
    async def chat(self, messages: list[dict], task: str = "chat", temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None, json_mode: bool = False,
                   tools: Optional[list] = None, tool_choice: str = "auto") -> LLMResponse:
        model = self.model_for(task)
        payload = self._payload(messages, model, temperature if temperature is not None
                                else settings.llm_temperature, max_tokens, json_mode)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        data = await self._request(payload)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        raw_usage = data.get("usage") or {}
        details = raw_usage.get("completion_tokens_details") or {}

        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        tool_calls = message.get("tool_calls") or []
        usage = self.build_usage(
            model=model,
            prompt_tokens=raw_usage.get("prompt_tokens", 0),
            completion_tokens=raw_usage.get("completion_tokens", 0),
            reasoning_tokens=details.get("reasoning_tokens", 0),
        )
        if usage.total_tokens == 0:
            usage = self.build_usage(model, estimate_tokens(json.dumps(messages, ensure_ascii=False)),
                                     estimate_tokens(content), estimated=True)
        return LLMResponse(content=content, reasoning=reasoning, usage=usage, tool_calls=tool_calls)

    # ---------- 流式 ----------
    async def stream(self, messages: list[dict], task: str = "chat",
                     temperature: Optional[float] = None) -> AsyncIterator[dict]:
        """逐块产出 {'type': 'delta'|'reasoning'|'done', ...}。"""
        model = self.model_for(task)
        payload = self._payload(messages, model, temperature if temperature is not None
                                else settings.llm_temperature, None, False)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}

        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage_data: dict = {}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "ignore")
                        raise LLMError(f"模型流式调用失败（{resp.status_code}）：{body[:300]}")
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            data = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        if data.get("usage"):
                            usage_data = data["usage"]
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        if delta.get("reasoning_content"):
                            reasoning_parts.append(delta["reasoning_content"])
                            yield {"type": "reasoning", "content": delta["reasoning_content"]}
                        if delta.get("content"):
                            content_parts.append(delta["content"])
                            yield {"type": "delta", "content": delta["content"]}
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise LLMError(f"模型流式调用失败：{exc}") from exc

        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
        if usage_data:
            details = usage_data.get("completion_tokens_details") or {}
            usage = self.build_usage(model, usage_data.get("prompt_tokens", 0),
                                     usage_data.get("completion_tokens", 0),
                                     details.get("reasoning_tokens", 0))
        else:
            usage = self.build_usage(model,
                                     estimate_tokens(json.dumps(messages, ensure_ascii=False)),
                                     estimate_tokens(content) + estimate_tokens(reasoning),
                                     estimated=True)
        yield {"type": "done", "content": content, "reasoning": reasoning, "usage": usage.to_dict()}


llm_client = DeepSeekClient()
