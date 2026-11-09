"""Agent 能力：让模型自己决定调哪个工具、调几次。

设计取舍：
- 只做只读工具（搜索 / 详情 / 相关 / 摘要），不碰采集写库，避免慢操作卡住循环；
- 规划阶段用非流式（快、token 少），拿到工具结果后再用流式输出最终答案；
- 最多 4 轮规划，超时或超步数就带着已有资料直接作答；
- 任何异常由调用方回退到单次 RAG，保证不比原来差。
"""
from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai import AISummary
from models.news import News
from services import rag
from services.llm_client import LLMError, llm_client

logger = logging.getLogger(__name__)

MAX_STEPS = 3              # 最多几轮工具规划
MAX_TOOL_CALLS = 5         # 一次问答最多执行几个工具
PLAN_TIMEOUT = 20          # 规划阶段总超时（秒）
MAX_FINAL_REFS = 8         # 最终回答最多带几条资料

# 命中这些词说明问题需要多步：对比、逐条、深挖、换词再搜
AGENT_HINTS = (
    "对比", "比较", "分别", "各自", "都有哪些", "哪些方面", "详细讲", "展开", "深入",
    "再查", "再搜", "多找", "每一篇", "逐条", "梳理", "按时间", "有什么不同", "区别",
)


def should_use_agent(question: str) -> bool:
    """规则分流：复杂问题走 Agent，简单问题继续走单次 RAG（便宜、快）。"""
    text = (question or "").strip()
    if len(text) >= 25:
        return True
    return any(word in text for word in AGENT_HINTS)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "按关键词搜索站内新闻，返回最相关的新闻标题、发布时间和摘要。"
                           "如果结果不理想，可以换更具体的关键词再搜一次。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，尽量具体，如「WTT 法兰克福」"},
                    "limit": {"type": "integer", "description": "返回条数，默认 6，最多 10"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news_detail",
            "description": "读取某一篇新闻的正文（前 1500 字），用于核对细节或回答追问。",
            "parameters": {
                "type": "object",
                "properties": {"news_id": {"type": "integer", "description": "新闻 id，来自搜索结果"}},
                "required": ["news_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "related_news",
            "description": "根据一篇新闻找内容相近的其他新闻，用于补充背景或做对比。",
            "parameters": {
                "type": "object",
                "properties": {
                    "news_id": {"type": "integer"},
                    "limit": {"type": "integer", "description": "返回条数，默认 4"},
                },
                "required": ["news_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_news",
            "description": "给某一篇新闻生成 100 字摘要 + 3 条要点（有缓存，重复调用不额外花钱）。",
            "parameters": {
                "type": "object",
                "properties": {"news_id": {"type": "integer"}},
                "required": ["news_id"],
            },
        },
    },
]

AGENT_SYSTEM = (
    "你是一个可以用工具的新闻助手。你可以调用工具检索站内新闻，规则：\n"
    "1. 先用 search_news 找资料；如果结果不相关或不够，换更具体的关键词再搜，但不要重复同样的搜索。\n"
    "2. 资料足够就直接回答，不要为了用工具而用工具。\n"
    "3. 回答必须基于工具返回的资料，引用时用 [1][2] 编号（编号对应资料顺序），不许编造。\n"
    "4. 每条资料都有发布时间，用户问「最新」时优先用日期最新的，并说明日期。\n"
    "5. 如果确实找不到，明确说「站内没有相关报道」，不要硬编。"
)


class AgentRunner:
    """执行「规划 → 调工具 → 拿结果 → 再规划」的循环，最后流式输出答案。"""

    def __init__(self, db: AsyncSession, news_id: Optional[int] = None) -> None:
        self.db = db
        self.news_id = news_id
        self.steps: list[dict] = []
        self.refs: dict[int, dict] = {}
        self.usage_total = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "cost": 0.0}
        self.tool_calls = 0

    # ---------- 工具实现 ----------
    def _add_ref(self, news: News, score: Optional[float] = None,
                 excerpt: Optional[str] = None) -> None:
        published = news.publish_time.strftime("%Y-%m-%d") if news.publish_time else ""
        if news.id in self.refs:
            if excerpt and len(excerpt) > len(self.refs[news.id].get("excerpt") or ""):
                self.refs[news.id]["excerpt"] = excerpt[:400]
            return
        self.refs[news.id] = {
            "newsId": news.id,
            "title": news.title,
            "publishTime": published,
            "score": round(float(score), 4) if score is not None else 0.5,
            "image": news.image,
            "excerpt": (excerpt or news.description or "")[:400],
        }

    async def _search_news(self, query: str, limit: int = 5) -> list[dict]:
        limit = max(1, min(int(limit or 5), 5))
        hits = await rag.search(self.db, query, top_k=limit)
        rows = []
        for hit in hits:
            rows.append({
                "news_id": hit["newsId"],
                "title": hit["title"],
                "publish_time": hit.get("publishTime"),
                "time": hit.get("publishTime"),
            })
            news = (await self.db.execute(select(News).where(News.id == hit["newsId"]))).scalar_one_or_none()
            if news:
                self._add_ref(news, hit.get("score"), excerpt=hit.get("content"))
        return rows

    async def _get_detail(self, news_id: int) -> dict:
        news = (await self.db.execute(select(News).where(News.id == news_id))).scalar_one_or_none()
        if not news:
            return {"error": "新闻不存在"}
        self._add_ref(news, excerpt=(news.content or "")[:400])
        return {
            "news_id": news.id,
            "title": news.title,
            "publish_time": news.publish_time.strftime("%Y-%m-%d %H:%M") if news.publish_time else None,
            "author": news.author,
            "content": (news.content or "")[:400],
        }

    async def _related(self, news_id: int, limit: int = 4) -> list[dict]:
        news = (await self.db.execute(select(News).where(News.id == news_id))).scalar_one_or_none()
        if not news:
            return []
        query = f"{news.title} {news.description or ''}"[:300]
        hits = await rag.search(self.db, query, top_k=limit + 1, min_score=0.2)
        rows = []
        for hit in hits:
            if hit["newsId"] == news_id:
                continue
            rows.append({"news_id": hit["newsId"], "title": hit["title"],
                         "publish_time": hit.get("publishTime")})
            related = (await self.db.execute(select(News).where(News.id == hit["newsId"]))).scalar_one_or_none()
            if related:
                self._add_ref(related, hit.get("score"))
        return rows[:limit]

    async def _summarize(self, news_id: int) -> dict:
        news = (await self.db.execute(select(News).where(News.id == news_id))).scalar_one_or_none()
        if not news:
            return {"error": "新闻不存在"}

        cached = (await self.db.execute(
            select(AISummary).where(AISummary.news_id == news_id)
        )).scalar_one_or_none()
        if cached:
            return {"news_id": news_id, "summary": cached.summary, "points": cached.points or [], "cached": True}

        prompt = f"标题：{news.title}\n正文：\n{(news.content or '')[:3000]}"
        result = await llm_client.chat(
            [{"role": "system", "content":
              '请输出 JSON：{"summary": "100字以内摘要", "points": ["要点1", "要点2", "要点3"]}'},
             {"role": "user", "content": prompt}],
            task="summary", max_tokens=500, json_mode=True,
        )
        self._accumulate(result.usage)
        raw = (result.content or "").strip().strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        try:
            parsed = json.loads(raw)
            summary = str(parsed.get("summary", ""))[:300]
            points = [str(p) for p in (parsed.get("points") or [])][:3]
        except json.JSONDecodeError:
            summary, points = raw[:300], []

        if summary:
            row = AISummary(news_id=news_id, summary=summary, points=points,
                            model=result.usage.model,
                            prompt_tokens=result.usage.prompt_tokens,
                            completion_tokens=result.usage.completion_tokens)
            self.db.add(row)
            await self.db.commit()
        self._add_ref(news)
        return {"news_id": news_id, "summary": summary, "points": points, "cached": False}

    async def _execute(self, call: dict) -> tuple[str, int]:
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}

        started = time.perf_counter()
        if name == "search_news":
            data = await self._search_news(**args)
            count = len(data)
        elif name == "get_news_detail":
            data = await self._get_detail(**args)
            count = 0 if "error" in data else 1
        elif name == "related_news":
            data = await self._related(**args)
            count = len(data)
        elif name == "summarize_news":
            data = await self._summarize(**args)
            count = 0 if "error" in data else 1
        else:
            data = {"error": f"未知工具 {name}"}
            count = 0

        latency = int((time.perf_counter() - started) * 1000)
        step = {
            "step": len(self.steps) + 1,
            "tool": name,
            "args": args,
            "count": count,
            "latencyMs": latency,
            "text": self._describe(name, args, count),
        }
        self.steps.append(step)
        self.tool_calls += 1
        return json.dumps(data, ensure_ascii=False), count

    @staticmethod
    def _describe(name: str, args: dict, count: int) -> str:
        if name == "search_news":
            return f"搜索「{args.get('query', '')}」· {count} 条"
        if name == "get_news_detail":
            return f"读取新闻 #{args.get('news_id')} 正文"
        if name == "related_news":
            return f"查找新闻 #{args.get('news_id')} 的相关报道 · {count} 条"
        if name == "summarize_news":
            return f"生成新闻 #{args.get('news_id')} 的摘要"
        return name

    def _accumulate(self, usage) -> None:
        self.usage_total["promptTokens"] += usage.prompt_tokens
        self.usage_total["completionTokens"] += usage.completion_tokens
        self.usage_total["totalTokens"] += usage.total_tokens
        self.usage_total["cost"] += usage.cost

    # ---------- 主流程 ----------
    async def run(self, question: str, history: Optional[list[dict]] = None) -> AsyncIterator[dict]:
        started = time.perf_counter()
        messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM}]
        for item in (history or [])[-4:]:
            if item.get("role") in ("user", "assistant") and item.get("content"):
                messages.append({"role": item["role"], "content": item["content"][:500]})
        messages.append({"role": "user", "content": question})

        direct_answer = ""
        for step_no in range(1, MAX_STEPS + 1):
            if time.perf_counter() - started > PLAN_TIMEOUT:
                logger.info("Agent 规划超时，提前作答")
                break

            try:
                resp = await llm_client.chat(messages, task="chat", tools=TOOLS,
                                             max_tokens=450, temperature=0.2)
            except LLMError:
                raise
            self._accumulate(resp.usage)

            if not resp.tool_calls:
                direct_answer = resp.content
                break

            messages.append({
                "role": "assistant",
                "content": resp.content or "",
                "tool_calls": resp.tool_calls,
            })
            for call in resp.tool_calls[:3]:
                if self.tool_calls >= MAX_TOOL_CALLS:
                    break
                result, _ = await self._execute(call)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                yield {"type": "step", **self.steps[-1]}

        refs = list(self.refs.values())[:MAX_FINAL_REFS]
        yield {"type": "refs", "refs": refs}

        if direct_answer and not self.steps:
            # 模型判断不需要工具，直接给答案
            for chunk in _split_chunks(direct_answer):
                yield {"type": "delta", "content": chunk}
            yield {"type": "done", "usage": self._usage_dict(), "steps": self.steps}
            return

        # 最终回答不再携带全部工具往返消息，只带「编号化的资料」，
        # 这样引用编号和 refs 顺序严格一致，也省掉大量 prompt token
        lines = []
        for i, ref in enumerate(refs, 1):
            lines.append(f"[{i}]《{ref['title']}》（{ref.get('publishTime') or '未知时间'}）\n{ref.get('excerpt') or ''}")
        context = "\n".join(lines)

        final_messages: list[dict] = [{"role": "system", "content": rag.SYSTEM_PROMPT}]
        for item in (history or [])[-4:]:
            if item.get("role") in ("user", "assistant") and item.get("content"):
                final_messages.append({"role": item["role"], "content": item["content"][:500]})
        final_messages.append({
            "role": "user",
            "content": f"参考资料：\n{context}\n\n用户问题：{question}",
        })

        collected: list[str] = []
        final_usage = None
        async for chunk in llm_client.stream(final_messages, task="chat"):
            if chunk["type"] == "delta":
                collected.append(chunk["content"])
                yield {"type": "delta", "content": chunk["content"]}
            elif chunk["type"] == "done":
                final_usage = chunk.get("usage")

        if final_usage:
            self.usage_total["promptTokens"] += final_usage.get("promptTokens", 0)
            self.usage_total["completionTokens"] += final_usage.get("completionTokens", 0)
            self.usage_total["totalTokens"] += final_usage.get("totalTokens", 0)
            self.usage_total["cost"] += final_usage.get("cost", 0)

        if not "".join(collected).strip():
            yield {"type": "delta", "content": "抱歉，这次没能整理出答案，请换个问法再试。"}

        yield {"type": "done", "usage": self._usage_dict(), "steps": self.steps}

    def _usage_dict(self) -> dict:
        return {
            "promptTokens": self.usage_total["promptTokens"],
            "completionTokens": self.usage_total["completionTokens"],
            "totalTokens": self.usage_total["totalTokens"],
            "cost": round(self.usage_total["cost"], 6),
            "model": llm_client.model_for("chat"),
            "estimated": False,
        }


def _split_chunks(text: str, size: int = 12) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]
