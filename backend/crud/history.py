# 浏览历史相关数据库操作
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.history import History
from models.news import News


async def add_history(db: AsyncSession, user_id: int, news_id: int) -> History:
    """添加浏览记录：同一篇新闻只留一条，重复浏览只刷新时间。"""
    existing = (await db.execute(
        select(History).where(History.user_id == user_id, History.news_id == news_id)
    )).scalar_one_or_none()

    if existing:
        existing.view_time = datetime.now()
        await db.commit()
        await db.refresh(existing)
        return existing

    history = History(user_id=user_id, news_id=news_id, view_time=datetime.now())
    db.add(history)
    await db.commit()
    await db.refresh(history)
    return history


async def get_history_list(db: AsyncSession, user_id: int, page: int = 1, page_size: int = 50):
    """获取浏览历史列表（分页），返回新闻详情和浏览时间"""
    count_stmt = select(func.count(History.id)).where(History.user_id == user_id)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    stmt = (
        select(History, News)
        .join(News, History.news_id == News.id)
        .where(History.user_id == user_id)
        .order_by(History.view_time.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    rows = result.all()

    news_list = []
    for history, news in rows:
        news_list.append({
            "id": history.id,          # 历史记录 id（删除时用）
            "historyId": history.id,
            "newsId": news.id,         # 新闻 id（跳转详情时用）
            "title": news.title,
            "description": news.description,
            "image": news.image,
            "author": news.author,
            "source": news.source,
            "publishTime": news.publish_time.isoformat() if news.publish_time else None,
            "categoryId": news.category_id,
            "views": news.views,
            "viewTime": history.view_time.isoformat() if history.view_time else None,
        })

    has_more = (offset + len(news_list)) < total

    return {
        "list": news_list,
        "total": total,
        "hasMore": has_more
    }


async def delete_history(db: AsyncSession, user_id: int, history_id: int) -> bool:
    """删除单条浏览记录"""
    stmt = delete(History).where(History.id == history_id, History.user_id == user_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def clear_history(db: AsyncSession, user_id: int) -> int:
    """清空所有浏览记录"""
    count_stmt = select(func.count(History.id)).where(History.user_id == user_id)
    count_result = await db.execute(count_stmt)
    count = count_result.scalar_one()

    stmt = delete(History).where(History.user_id == user_id)
    await db.execute(stmt)
    await db.commit()

    return count
