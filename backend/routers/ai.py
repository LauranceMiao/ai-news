"""AI 接口：单篇摘要、RAG 问答(SSE)、今日要闻、语义相关新闻、会话历史。"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.db_conf import AsyncSessionLocal, get_db
from models.ai import AIMessage, AISession, AISummary
from models.news import News
from models.users import User
from schemas.ai import ChatRequest, SummaryRequest
from services import digest as digest_service
from services import rag
from services.agent import AgentRunner, should_use_agent
from services.cache import cache
from services.embeddings import EmbeddingError
from services.llm_client import LLMError, llm_client
from utils.auth import get_current_user, get_optional_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])

SUMMARY_SYSTEM = (
    "你是一名新闻编辑。请阅读新闻正文，输出 JSON，字段为：\n"
    '{"summary": "100字以内的中文摘要", "points": ["要点1", "要点2", "要点3"]}\n'
    "要点不超过 3 条，每条 25 字以内，只依据正文内容，不要编造。"
)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ------------------------- 摘要 -------------------------
@router.post("/summary")
async def news_summary(body: SummaryRequest, db: AsyncSession = Depends(get_db)):
    news = (await db.execute(select(News).where(News.id == body.newsId))).scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=404, detail="新闻不存在")

    cached = (await db.execute(
        select(AISummary).where(AISummary.news_id == body.newsId)
    )).scalar_one_or_none()
    if cached and not body.force:
        return {
            "code": 200,
            "message": "ok",
            "data": {
                "newsId": news.id,
                "summary": cached.summary,
                "points": cached.points or [],
                "model": cached.model,
                "cached": True,
                "usage": {"promptTokens": cached.prompt_tokens,
                          "completionTokens": cached.completion_tokens,
                          "totalTokens": cached.prompt_tokens + cached.completion_tokens,
                          "cost": round(
                              cached.prompt_tokens / 1_000_000 * llm_client.price_for(cached.model or "")[0]
                              + cached.completion_tokens / 1_000_000 * llm_client.price_for(cached.model or "")[1], 6),
                          "model": cached.model},
            },
        }

    content = (news.content or "")[:3000]
    prompt = f"标题：{news.title}\n正文：\n{content}"
    try:
        result = await llm_client.chat(
            [{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": prompt}],
            task="summary", max_tokens=500, json_mode=True,
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    raw = result.content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1]
    try:
        parsed = json.loads(raw)
        summary = str(parsed.get("summary", "")).strip()
        points = [str(p) for p in (parsed.get("points") or [])][:3]
    except json.JSONDecodeError:
        summary, points = raw[:300], []

    if not summary:
        raise HTTPException(status_code=502, detail="模型未返回有效摘要")

    if cached:
        cached.summary = summary
        cached.points = points
        cached.model = result.usage.model
        cached.prompt_tokens = result.usage.prompt_tokens
        cached.completion_tokens = result.usage.completion_tokens
    else:
        db.add(AISummary(
            news_id=news.id, summary=summary, points=points,
            model=result.usage.model,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
        ))
    await db.commit()

    return {
        "code": 200,
        "message": "ok",
        "data": {
            "newsId": news.id,
            "summary": summary,
            "points": points,
            "model": result.usage.model,
            "cached": False,
            "usage": result.usage.to_dict(),
        },
    }


# ------------------------- 问答（SSE） -------------------------
@router.post("/chat")
async def ai_chat(body: ChatRequest,
                  mode: str = Query(default="auto", description="auto / rag / agent"),
                  db: AsyncSession = Depends(get_db),
                  user: Optional[User] = Depends(get_optional_user)):
    started = time.perf_counter()

    use_agent = mode == "agent" or (mode == "auto" and should_use_agent(body.question))

    try:
        hits = await rag.search(db, body.question, news_id=body.newsId)
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # 索引为空等情况降级为无检索
        logger.warning("检索失败，降级为纯模型回答：%s", exc)
        hits = []

    messages = rag.build_messages(body.question, hits, body.history)
    refs = [{"newsId": h["newsId"], "title": h["title"], "score": h["score"],
             "image": h["image"]} for h in hits]

    session_id = body.sessionId
    need_new_session = session_id is None
    owner_id = user.id if user else None
    if session_id is not None:
        session = (await db.execute(select(AISession).where(AISession.id == session_id))).scalar_one_or_none()
        # 会话不存在、或归属不是当前用户（换了账号 / 匿名会话被登录用户接手）→ 开新会话
        if not session or session.user_id != owner_id:
            need_new_session = True

    if need_new_session:
        session = AISession(user_id=user.id if user else None, title=body.question[:40])
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

    async def event_stream():
        answer_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage = None
        steps: list[dict] = []
        final_refs = refs

        yield _sse({"type": "meta", "sessionId": session_id, "refs": refs,
                    "mode": "agent" if use_agent else "rag"})

        if use_agent:
            runner = AgentRunner(db, news_id=body.newsId)
            try:
                async for event in runner.run(body.question, body.history):
                    etype = event["type"]
                    if etype == "delta":
                        answer_parts.append(event["content"])
                        yield _sse(event)
                    elif etype == "step":
                        steps.append(event)
                        yield _sse(event)
                    elif etype == "refs":
                        if event["refs"]:
                            final_refs = event["refs"]
                        yield _sse(event)
                    elif etype == "done":
                        usage = event.get("usage")
                        yield _sse({**event, "refs": final_refs, "sessionId": session_id})
                logger.info("Agent 完成：%s 步，%s", len(steps), usage)
            except Exception as exc:
                # 任何异常都回退到单次 RAG，避免比原来更差
                logger.warning("Agent 执行失败，回退单次 RAG：%s", exc)
                steps = []
                yield _sse({"type": "notice", "message": "已切换为快速模式"})
                async for chunk in llm_client.stream(messages, task="chat"):
                    if chunk["type"] == "delta":
                        answer_parts.append(chunk["content"])
                        yield _sse({"type": "delta", "content": chunk["content"]})
                    elif chunk["type"] == "done":
                        usage = chunk.get("usage")
        else:
            try:
                async for chunk in llm_client.stream(messages, task="analysis" if body.newsId else "chat"):
                    if chunk["type"] == "delta":
                        answer_parts.append(chunk["content"])
                        yield _sse({"type": "delta", "content": chunk["content"]})
                    elif chunk["type"] == "reasoning":
                        reasoning_parts.append(chunk["content"])
                        yield _sse({"type": "reasoning", "content": chunk["content"]})
                    elif chunk["type"] == "done":
                        usage = chunk["usage"]
            except LLMError as exc:
                yield _sse({"type": "error", "message": str(exc)})
                yield "data: [DONE]\n\n"
                return

        answer = "".join(answer_parts)
        if not answer.strip():
            answer = "抱歉，模型这次没有返回正文（可能思考过长被截断），请换个问法再试一次。"
            yield _sse({"type": "delta", "content": answer})
        latency = int((time.perf_counter() - started) * 1000)
        try:
            async with AsyncSessionLocal() as save_db:
                save_db.add(AIMessage(session_id=session_id, role="user",
                                      content=body.question, refs=refs))
                save_db.add(AIMessage(
                    session_id=session_id, role="assistant", content=answer,
                    reasoning="".join(reasoning_parts) or None, refs=final_refs,
                    steps=steps or None,
                    prompt_tokens=(usage or {}).get("promptTokens", 0),
                    completion_tokens=(usage or {}).get("completionTokens", 0),
                    latency_ms=latency,
                ))
                await save_db.commit()
        except Exception as exc:
            logger.warning("保存会话失败：%s", exc)

        yield _sse({"type": "done", "usage": usage, "latencyMs": latency,
                    "refs": final_refs, "sessionId": session_id, "steps": steps})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------- 今日要闻 -------------------------
@router.get("/daily")
async def daily_digest(
    digest_date: Optional[str] = Query(None, alias="date", description="YYYY-MM-DD"),
    category_id: Optional[int] = Query(None, alias="categoryId"),
    force: bool = False,
    db: AsyncSession = Depends(get_db),
):
    day = date.fromisoformat(digest_date) if digest_date else date.today()
    try:
        data = await digest_service.get_daily_digest(db, day, category_id, force)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"code": 200, "message": "ok", "data": data}


# ------------------------- 语义相关新闻 -------------------------
@router.get("/related")
async def related_news(
    news_id: int = Query(..., alias="newsId"),
    limit: int = 5,
    db: AsyncSession = Depends(get_db),
):
    news = (await db.execute(select(News).where(News.id == news_id))).scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=404, detail="新闻不存在")

    query = f"{news.title} {news.description or ''}"[:500]
    try:
        hits = await rag.search(db, query, top_k=limit + 1, min_score=0.2)
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    items = [h for h in hits if h["newsId"] != news_id][:limit]
    return {"code": 200, "message": "ok", "data": items}


# ------------------------- 会话历史 -------------------------
@router.get("/sessions")
async def list_sessions(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    sessions = (await db.execute(
        select(AISession).where(AISession.user_id == user.id).order_by(AISession.updated_at.desc()).limit(50)
    )).scalars().all()
    return {"code": 200, "data": [
        {"id": s.id, "title": s.title, "updatedAt": s.updated_at.strftime("%Y-%m-%d %H:%M")}
        for s in sessions
    ]}


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: int, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    session = (await db.execute(select(AISession).where(AISession.id == session_id))).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该会话")

    messages = (await db.execute(
        select(AIMessage).where(AIMessage.session_id == session_id).order_by(AIMessage.id.asc())
    )).scalars().all()
    return {"code": 200, "data": [
        {"id": m.id, "role": m.role, "content": m.content, "refs": m.refs,
         "steps": m.steps,
         "createdAt": m.created_at.strftime("%Y-%m-%d %H:%M")}
        for m in messages
    ]}


# ------------------------- 运维/演示 -------------------------
@router.get("/stats")
async def ai_stats(db: AsyncSession = Depends(get_db)):
    store = await rag.get_store(db)
    return {
        "code": 200,
        "data": {
            "chunks": int(store.matrix.shape[0]),
            "dim": int(store.matrix.shape[1]) if store.matrix.shape[0] else 0,
            "cache": cache.stats(),
        },
    }


@router.post("/reindex")
async def reindex(
    news_id: Optional[int] = Query(None, alias="newsId"),
    force: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """建索引（开发和演示用；生产应改为后台任务）。"""
    try:
        result = await rag.index_news(db, [news_id] if news_id else None, force=force)
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"code": 200, "message": "ok", "data": result}
