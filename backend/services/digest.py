"""今日要闻：按天聚合新闻，调用 pro 模型生成一段总览，并入库缓存。"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai import AIDigest
from models.news import Category, News
from services.llm_client import llm_client, LLMError

logger = logging.getLogger(__name__)

DIGEST_SYSTEM = (
    "你是一名资深新闻主编。请根据给定的新闻列表，写一段「今日要闻」总览，要求：\n"
    "1. 开头一句话概括今天的整体热点；\n"
    "2. 用 3-5 个要点分别提炼最重要的事件，每条 40 字以内，句末标注来源编号如 [1]；\n"
    "3. 只使用给定信息，不要编造；语气客观，总字数 300 字以内。"
)


def _dedupe(rows, limit: int):
    """按标题去重，避免同一事件在要闻里出现多次。"""
    seen, result = set(), []
    for news in rows:
        title = (news.title or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        result.append(news)
        if len(result) >= limit:
            break
    return result


async def _pick_news(db: AsyncSession, day: date, category_id: Optional[int], limit: int = 15):
    # 热搜话题只有标题没有正文，不放进要闻，保证每条引用点开都能读
    base = select(News).where(News.source != "baidu_hot")
    if category_id:
        base = base.where(News.category_id == category_id)

    # 1) 当天
    start = datetime.combine(day, datetime.min.time())
    rows = (await db.execute(
        base.where(News.publish_time >= start, News.publish_time < start + timedelta(days=1))
        .order_by(News.views.desc()).limit(limit * 3)
    )).scalars().all()
    if rows:
        return _dedupe(rows, limit)

    # 2) 最近 48 小时（采集来的实时新闻）
    rows = (await db.execute(
        base.where(News.publish_time >= datetime.now() - timedelta(hours=48))
        .order_by(News.publish_time.desc()).limit(limit * 3)
    )).scalars().all()
    if rows:
        return _dedupe(rows, limit)

    # 3) 最近 7 天
    rows = (await db.execute(
        base.where(News.publish_time >= datetime.now() - timedelta(days=7))
        .order_by(News.publish_time.desc()).limit(limit * 3)
    )).scalars().all()
    if rows:
        return _dedupe(rows, limit)

    # 4) 兜底：库里最新的一批
    rows = (await db.execute(
        base.order_by(News.publish_time.desc()).limit(limit * 3)
    )).scalars().all()
    return _dedupe(rows, limit)


async def get_daily_digest(db: AsyncSession, digest_date: Optional[date] = None,
                           category_id: Optional[int] = None, force: bool = False) -> dict:
    day = digest_date or date.today()

    cached = (await db.execute(
        select(AIDigest).where(AIDigest.digest_date == day, AIDigest.category_id == category_id)
    )).scalar_one_or_none()
    if cached and cached.content.strip() and not force:
        return {
            "date": str(cached.digest_date),
            "categoryId": cached.category_id,
            "content": cached.content,
            "refs": cached.refs or [],
            "model": cached.model,
            "usage": {
                "promptTokens": cached.prompt_tokens,
                "completionTokens": cached.completion_tokens,
            },
            "cached": True,
        }

    news_list = await _pick_news(db, day, category_id)
    if not news_list:
        return {"date": str(day), "categoryId": category_id, "content": "暂无新闻数据。",
                "refs": [], "model": None, "cached": False}

    category_name = None
    if category_id:
        category_name = (await db.execute(
            select(Category.name).where(Category.id == category_id)
        )).scalar_one_or_none()

    lines = []
    refs = []
    for i, n in enumerate(news_list, 1):
        desc = (n.description or "")[:120]
        lines.append(f"[{i}] {n.title}｜{desc}")
        refs.append({"newsId": n.id, "title": n.title, "image": n.image})

    scope = f"「{category_name}」频道" if category_name else "全站"
    user_prompt = f"日期：{day}\n范围：{scope}\n新闻列表：\n" + "\n".join(lines)

    try:
        result = await llm_client.chat(
            [{"role": "system", "content": DIGEST_SYSTEM}, {"role": "user", "content": user_prompt}],
            task="digest",
            max_tokens=2500,
        )
        content = result.content.strip()
        usage = result.usage
        model = usage.model
        if not content:
            raise LLMError("模型只返回了思考过程，没有正文")
    except LLMError as exc:
        logger.warning("今日要闻生成失败，返回列表兜底：%s", exc)
        content = "今日要闻生成失败，先看这些热点：\n" + "\n".join(
            f"{i}. {n.title}" for i, n in enumerate(news_list[:5], 1)
        )
        usage = None
        model = None

    if cached:
        cached.content = content
        cached.refs = refs
        cached.model = model
        cached.prompt_tokens = usage.prompt_tokens if usage else 0
        cached.completion_tokens = usage.completion_tokens if usage else 0
    else:
        db.add(AIDigest(
            digest_date=day,
            category_id=category_id,
            content=content,
            refs=refs,
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        ))
    await db.commit()

    return {
        "date": str(day),
        "categoryId": category_id,
        "content": content,
        "refs": refs,
        "model": model,
        "usage": usage.to_dict() if usage else None,
        "cached": False,
    }
