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
import re
import time
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai import AISummary
from models.news import News
from services import rag
from services.llm_client import LLMError, llm_client

logger = logging.getLogger(__name__)

MAX_STEPS = 3              # 普通问答最多几轮规划
MAX_STEPS_TASK = 3         # 任务模式最多几轮规划
MAX_TOOL_CALLS = 4         # 普通问答最多执行几个工具
MAX_TOOL_CALLS_TASK = 4    # 任务模式最多执行几个工具
PLAN_TIMEOUT = 30          # 规划阶段总超时（秒）
MAX_FINAL_REFS = 8         # 最终回答最多带几条资料

def _budget_hint(remaining: int) -> str:
    """在工具结果后附上剩余预算，让模型自己判断该不该收尾。"""
    if remaining <= 0:
        return " [hint] 工具调用次数已用尽，必须立即调用 finish_answer 结束检索并作答。"
    if remaining == 1:
        return " [hint] 只剩 1 次工具调用，除非关键信息缺失，否则立即调用 finish_answer。"
    return f" [hint] 还剩 {remaining} 次工具调用；信息已够用时请立即调用 finish_answer，不要继续搜索。"
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
    {
        "type": "function",
        "function": {
            "name": "finish_answer",
            "description": "当已收集到的资料足以回答问题、或已经确认站内没有相关内容时调用，"
                           "表示结束检索并进入作答。调用后不会再检索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "一句话说明为什么可以停了，例如「已覆盖科技、财经两方面」"}
                },
                "required": ["reason"],
            },
        },
    },
]

AGENT_SYSTEM = (
    "你是一个可以用工具的新闻助手。你可以调用工具检索站内新闻，规则：\n"
    "1. 先用 search_news 找资料；结果不相关或为空时换同义或更具体的关键词再搜，不要重复同一查询。\n"
    "2. 资料足够就调用 finish_answer 结束检索。通常 1-2 次搜索即可，最多 2 轮检索，之后必须 finish_answer。\n"
    "3. 回答必须基于工具返回的资料，引用时用 [1][2] 编号（编号对应资料顺序），不许编造。\n"
    "4. 每条资料都有发布时间，用户问「最新」时优先用日期最新的，并说明日期。\n"
    "5. 如果确实找不到，明确说「站内没有相关报道」，不要硬编。"
)

TASK_SYSTEM = (
    "你是一个可以调用工具的新闻研究助手，用户会给你一个「任务」而不是简单问题。规则：\n"
    "1. 先把任务拆成 2-4 个要查的方面（心里规划即可，不必输出）。\n"
    "2. 针对每个方面调用 search_news（关键词要具体，避免重复查询），最多 3 轮检索，之后必须 finish_answer。\n"
    "3. 资料覆盖任务要求后，调用 finish_answer 结束检索，理由里写清覆盖了哪些方面。\n"
    "4. 最终输出要结构化：先一句结论，再分点列出条目，每条句末用 [1][2] 标注来源编号。\n"
    "5. 只使用工具返回的资料，不许编造；资料不足时明确说明缺什么。"
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
                self.refs[news.id]["excerpt"] = excerpt[:300]
            return
        self.refs[news.id] = {
            "newsId": news.id,
            "title": news.title,
            "publishTime": published,
            "score": round(float(score), 4) if score is not None else 0.5,
            "image": news.image,
            "excerpt": (excerpt or news.description or "")[:300],
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
        if not rows:
            return [{"hint": "没有检索到结果，请换更具体或同义的关键词重试，不要重复同一查询"}]
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

    async def _ask_finish(self, messages: list[dict]) -> str:
        """预算用尽后，强制模型做一次终止判断，返回它给出的理由。"""
        finish_tool = [tool for tool in TOOLS
                       if tool["function"]["name"] == "finish_answer"]
        try:
            resp = await llm_client.chat(
                messages + [{"role": "user",
                             "content": "工具预算已用尽，请判断现有资料是否足以回答问题，并调用 finish_answer 说明理由。"}],
                task="chat", tools=finish_tool,
                max_tokens=150, temperature=0.2,
            )
        except LLMError as exc:
            logger.warning("终止判断失败：%s", exc)
            return ""
        self._accumulate(resp.usage)
        for call in resp.tool_calls:
            if call["function"]["name"] == "finish_answer":
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    return "资料已足够"
                return str(args.get("reason") or "资料已足够")
        return ""

    # ---------- 主流程 ----------
    @staticmethod
    def _sanitize_citations(text: str, max_ref: int) -> tuple[str, list[int]]:
        """校验引用编号：超出参考范围的 [n] 直接剔除，避免指向不存在的资料。"""
        bad: set[int] = set()

        def repl(match):
            number = int(match.group(1))
            if 1 <= number <= max_ref:
                return match.group(0)
            bad.add(number)
            return ""

        return re.sub(r"\[(\d{1,2})\]", repl, text), sorted(bad)

    async def run(self, question: str, history: Optional[list[dict]] = None,
                  task_mode: bool = False) -> AsyncIterator[dict]:
        started = time.perf_counter()
        max_steps = MAX_STEPS_TASK if task_mode else MAX_STEPS
        max_calls = MAX_TOOL_CALLS_TASK if task_mode else MAX_TOOL_CALLS
        system_prompt = (TASK_SYSTEM if task_mode else AGENT_SYSTEM) + f"\n本次最多可调用 {max_calls} 次工具，每次搜索会返回 5 条标题，通常已足够，请节约调用。"

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for item in (history or [])[-4:]:
            if item.get("role") in ("user", "assistant") and item.get("content"):
                messages.append({"role": item["role"], "content": item["content"][:500]})
        messages.append({"role": "user", "content": question})

        direct_answer = ""
        finish_reason = ""
        for round_index in range(1, max_steps + 1):
            if time.perf_counter() - started > PLAN_TIMEOUT:
                finish_reason = "规划超时，使用已有资料作答"
                logger.info("Agent 规划超时，提前作答")
                break

            resp = await llm_client.chat(messages, task="chat", tools=TOOLS,
                                         max_tokens=450, temperature=0.2)
            self._accumulate(resp.usage)

            if not resp.tool_calls:
                direct_answer = resp.content
                finish_reason = "模型直接作答"
                break

            # 只保留真正会执行的工具调用：assistant 消息里的 tool_calls
            # 必须与后续 tool 消息一一对应，否则 DeepSeek 会报 400
            finish_calls = [c for c in resp.tool_calls
                            if c["function"]["name"] == "finish_answer"]
            calls = [finish_calls[0]] if finish_calls else resp.tool_calls[:2]

            assistant_msg = {
                "role": "assistant",
                "content": resp.content or "",
                "tool_calls": calls,
            }
            # 思考模式要求把 reasoning_content 一并回传，否则下一次调用会 400
            if resp.reasoning:
                assistant_msg["reasoning_content"] = resp.reasoning
            messages.append(assistant_msg)

            # 模型显式调用 finish_answer：认为资料已足够，结束检索
            if finish_calls:
                try:
                    args = json.loads(finish_calls[0]["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                finish_reason = str(args.get("reason") or "资料已足够")
                step = {
                    "step": len(self.steps) + 1,
                    "tool": "finish_answer",
                    "args": args,
                    "count": 0,
                    "latencyMs": 0,
                    "text": f"判断可以作答：{finish_reason}",
                }
                self.steps.append(step)
                yield {"type": "step", **step}
                break

            for call in calls:
                if self.tool_calls >= max_calls:
                    # 预算用尽也要回一条 tool 消息，保证 tool_calls 有对应响应
                    messages.append({"role": "tool", "tool_call_id": call["id"],
                                     "content": '{"skipped": true, "reason": "工具调用次数已达上限"}'})
                    continue
                result, _ = await self._execute(call)
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": result + _budget_hint(max_calls - self.tool_calls)})
                yield {"type": "step", **self.steps[-1]}

            # 工具预算刚好用尽：单独问一次「现在能不能作答」，
            # 让终止理由由模型给出，而不是硬编码的“达到上限”
            if self.tool_calls >= max_calls or round_index >= max_steps:
                reason = await self._ask_finish(messages) or "预算用尽，使用已有资料作答"
                if reason:
                    finish_reason = reason
                    step = {
                        "step": len(self.steps) + 1,
                        "tool": "finish_answer",
                        "args": {"reason": reason},
                        "count": 0,
                        "latencyMs": 0,
                        "text": f"判断可以作答：{reason}",
                    }
                    self.steps.append(step)
                    yield {"type": "step", **step}
                break
        else:
            finish_reason = "达到步数上限，使用已有资料作答"

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

        answer = "".join(collected)
        if not answer.strip():
            answer = "抱歉，这次没能整理出答案，请换个问法再试。"
            yield {"type": "delta", "content": answer}

        # 引用校验：把指向不存在资料的 [n] 去掉，并告知前端替换正文
        fixed, bad_refs = self._sanitize_citations(answer, len(refs))
        if bad_refs:
            answer = fixed
            yield {
                "type": "fix",
                "content": fixed,
                "notice": f"已移除 {len(bad_refs)} 处无效引用（[{', '.join(map(str, bad_refs))}]）",
            }

        yield {
            "type": "done",
            "usage": self._usage_dict(),
            "steps": self.steps,
            "answer": answer,
            "finishReason": finish_reason,
        }

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
