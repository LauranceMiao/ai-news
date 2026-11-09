#封装数据库增删改查等功能


from models.news import News
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from models.news import Category


async def get_categories(db:AsyncSession,skip:int=0,limit:int=100):
    stmt = select(Category).offset(skip).limit(limit)
    result=await db.execute(stmt)
    return result.scalars().all()

async def get_news_list(db: AsyncSession, category_id: int, skip: int = 0, limit: int = 10,
                        only_live: bool = False, include_hot: bool = False):
        # 查询指定分类下的新闻，按发布时间倒序（新采集的排前面）
        stmt = select(News).where(News.category_id == category_id)
        if only_live:
            stmt = stmt.where(News.source != "seed")
        if not include_hot:
            stmt = stmt.where(News.source != "baidu_hot")
        stmt = stmt.order_by(News.publish_time.desc(), News.hot_score.desc(), News.id.desc()).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

async def get_news_count(db: AsyncSession, category_id: int, only_live: bool = False,
                         include_hot: bool = False):
        # 查询的是指定分类下的新闻数量
        stmt = select(func.count(News.id)).where(News.category_id == category_id)
        if only_live:
            stmt = stmt.where(News.source != "seed")
        if not include_hot:
            stmt = stmt.where(News.source != "baidu_hot")
        result = await db.execute(stmt)
        return result.scalar_one()  # 只能有一个结果，否则报错


async def get_news_detail(db: AsyncSession, news_id: int):
    stmt = select(News).where(News.id == news_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()



#增加浏览量+1
async def increase_news_view(db: AsyncSession,  news_id: int):
    stmt = update(News).where(News.id == news_id).values(views=News.views + 1)
    result = await db.execute(stmt)
    await db.commit()

    #数据库更新，需要检查数据库是否命中了（数据是否更新了）->命中了返回true
    return result.rowcount > 0


#获取同类型的新闻
async def get_related_news(db: AsyncSession, news_id: int,category_id: int,limit: int = 5):
    #随机获取同类型新闻
    stmt = select(News).where(
        News.category_id == category_id,
        News.id != news_id
    ).order_by(
        func.rand()
    ).limit(limit)
    result = await db.execute(stmt)
    #return result.scalars().all()
    related_news = result.scalars().all()
    return[{
        "id": news_detail.id,
        "title": news_detail.title,
        "content": news_detail.content,
        "image": news_detail.image,
        "author": news_detail.author,
        "publishTime": news_detail.publish_time,
        "categoryId": news_detail.category_id,
        "views": news_detail.views,
    } for news_detail in related_news]

