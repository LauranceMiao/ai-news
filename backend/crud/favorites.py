# 收藏相关数据库操作
from sqlalchemy import select, func, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from models.favorites import Favorite
from models.news import News


async def check_favorite(db: AsyncSession, user_id: int, news_id: int) -> bool:
    """检查某条新闻是否已被收藏"""
    stmt = select(Favorite).where(
        and_(Favorite.user_id == user_id, Favorite.news_id == news_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def add_favorite(db: AsyncSession, user_id: int, news_id: int) -> Favorite:
    """添加收藏"""
    favorite = Favorite(user_id=user_id, news_id=news_id)
    db.add(favorite)
    await db.commit()
    await db.refresh(favorite)
    return favorite


async def remove_favorite(db: AsyncSession, user_id: int, news_id: int) -> bool:
    """取消收藏，返回是否成功删除"""
    stmt = delete(Favorite).where(
        and_(Favorite.user_id == user_id, Favorite.news_id == news_id)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def get_favorite_list(db: AsyncSession, user_id: int, page: int = 1, page_size: int = 10):
    """获取收藏列表（分页），返回新闻详情和收藏时间"""
    # 查询收藏记录总数
    count_stmt = select(func.count(Favorite.id)).where(Favorite.user_id == user_id)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    # 分页查询收藏记录，关联新闻表
    offset = (page - 1) * page_size
    stmt = (
        select(Favorite, News)
        .join(News, Favorite.news_id == News.id)
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    rows = result.all()

    # 组装返回数据
    news_list = []
    for favorite, news in rows:
        news_list.append({
            "id": news.id,
            "title": news.title,
            "description": news.description,
            "image": news.image,
            "author": news.author,
            "publishTime": news.publish_time.isoformat() if news.publish_time else None,
            "categoryId": news.category_id,
            "views": news.views,
            "favoriteTime": favorite.created_at.isoformat() if favorite.created_at else None,
        })

    has_more = (offset + len(news_list)) < total

    return {
        "list": news_list,
        "total": total,
        "hasMore": has_more
    }


async def clear_favorites(db: AsyncSession, user_id: int) -> int:
    """清空所有收藏，返回删除数量"""
    # 先统计数量
    count_stmt = select(func.count(Favorite.id)).where(Favorite.user_id == user_id)
    count_result = await db.execute(count_stmt)
    count = count_result.scalar_one()

    # 执行删除
    stmt = delete(Favorite).where(Favorite.user_id == user_id)
    await db.execute(stmt)
    await db.commit()

    return count
