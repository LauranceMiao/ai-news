"""新闻接口：分类、列表、详情，以及「手动刷新」采集。"""
import asyncio
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.db_conf import AsyncSessionLocal, get_db
from config.settings import settings
from crud import news
from models.news import News
from services import collectors, rag

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/news", tags=["news"])

# 手动刷新的状态机（单进程内共享）
_refresh_state: dict = {
    "status": "idle",   # idle / running / done / error
    "startedAt": None,
    "finishedAt": None,
    "added": 0,
    "message": "",
    "result": None,
}
_refresh_task: asyncio.Task | None = None
_last_refresh_ts: float = 0.0
REFRESH_COOLDOWN = settings.refresh_cooldown  # 秒


@router.get("/categories")
async def get_categories(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    categories = await news.get_categories(db, skip, limit)
    return {"code": 200, "message": "获取分类成功", "data": categories}


def _to_item(n: News) -> dict:
    """列表项统一转成前端用的驼峰字段。"""
    return {
        "id": n.id,
        "title": n.title,
        "description": n.description,
        "image": n.image,
        "author": n.author,
        "source": n.source,
        "sourceUrl": n.source_url,
        "hotScore": n.hot_score or 0,
        "publishTime": n.publish_time.strftime("%Y-%m-%d %H:%M") if n.publish_time else "",
        "categoryId": n.category_id,
        "views": n.views,
    }


@router.get("/list")
async def get_news_list(
    category_id: int = Query(default=..., alias="categoryId"),
    page: int = 1,
    page_size: int = Query(default=10, alias="pageSize", le=100),
    only_live: bool = Query(default=False, alias="onlyLive", description="只看采集来的新闻"),
    include_hot: bool = Query(default=False, alias="includeHot", description="是否包含热搜话题（默认不包含，热搜单独接口）"),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size

    news_list = await news.get_news_list(db, category_id, offset, page_size, only_live, include_hot)
    total = await news.get_news_count(db, category_id, only_live, include_hot)

    has_more = (offset + len(news_list)) < total
    return {
        "code": 200,
        "message": "获取新闻列表成功",
        "data": {"list": [_to_item(n) for n in news_list], "total": total, "hasMore": has_more},
    }


@router.get("/hot")
async def get_hot_list(limit: int = Query(default=20, ge=1, le=50),
                       db: AsyncSession = Depends(get_db)):
    """热搜话题榜：只有标题和热度，正文在站外，详情页给出跳转。"""
    rows = (await db.execute(
        select(News).where(News.source == "baidu_hot")
        .order_by(News.hot_score.desc(), News.id.desc()).limit(limit)
    )).scalars().all()
    return {"code": 200, "message": "ok", "data": [_to_item(n) for n in rows]}


@router.get("/search")
async def search_news(
    q: str = Query(..., min_length=1, max_length=50, description="搜索关键词"),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """新闻搜索：标题关键词优先，再补语义（向量）召回，最后兜底正文模糊匹配。

    短查询（如「降雪」）纯语义效果差，所以标题命中排最前。
    """
    keyword = q.strip()
    if not keyword:
        return {"code": 200, "message": "ok", "data": {"list": [], "mode": "empty"}}

    like = f"%{keyword}%"
    items: list[dict] = []
    seen: set[int] = set()

    # 1) 标题命中：最准，按时间倒序
    title_rows = (await db.execute(
        select(News).where(News.title.like(like))
        .order_by(News.publish_time.desc(), News.id.desc()).limit(limit)
    )).scalars().all()
    for n in title_rows:
        item = _to_item(n)
        item["match"] = "title"
        items.append(item)
        seen.add(n.id)

    # 2) 语义召回：补充标题里没出现关键词、但内容相关的新闻
    #    短词（1-2 字）语义容易跑偏（「降雪」召回「降准」），只用关键词补正文
    if len(items) < limit and len(keyword) >= 3:
        try:
            hits = await rag.search(db, keyword, top_k=limit, min_score=0.35)
            ids = [h["newsId"] for h in hits if h["newsId"] not in seen][: limit - len(items)]
            if ids:
                rows = (await db.execute(select(News).where(News.id.in_(ids)))).scalars().all()
                by_id = {n.id: n for n in rows}
                score_map = {h["newsId"]: h["score"] for h in hits}
                for news_id in ids:
                    n = by_id.get(news_id)
                    if not n:
                        continue
                    item = _to_item(n)
                    item["match"] = "semantic"
                    item["score"] = round(float(score_map.get(news_id, 0)), 4)
                    items.append(item)
                    seen.add(news_id)
        except Exception as exc:  # 模型未加载/索引为空时不影响关键词搜索
            logger.warning("语义搜索不可用：%s", exc)

    # 3) 兜底：正文里包含关键词
    if len(items) < limit:
        rows = (await db.execute(
            select(News).where(
                or_(News.title.like(like), News.description.like(like), News.content.like(like))
            )
            .order_by(News.publish_time.desc(), News.id.desc()).limit(limit)
        )).scalars().all()
        for n in rows:
            if n.id in seen:
                continue
            item = _to_item(n)
            item["match"] = "keyword"
            items.append(item)
            seen.add(n.id)

    mode = "hybrid" if any(i.get("match") == "semantic" for i in items) else ("title" if items else "none")
    return {"code": 200, "message": "ok", "data": {"list": items[:limit], "mode": mode}}


@router.get("/detail")
async def get_news_detail(news_id: int = Query(default=..., alias="id"), db: AsyncSession = Depends(get_db)):
    news_detail = await news.get_news_detail(db, news_id)
    if not news_detail:
        raise HTTPException(status_code=404, detail="新闻不存在")

    views_res = await news.increase_news_view(db, news_detail.id)
    if not views_res:
        raise HTTPException(status_code=404, detail="新闻不存在")

    related_news = await news.get_related_news(db, news_detail.id, news_detail.category_id)

    return {
        "code": 200,
        "message": "success",
        "data": {
            "id": news_detail.id,
            "title": news_detail.title,
            "description": news_detail.description,
            "content": news_detail.content,
            "image": news_detail.image,
            "author": news_detail.author,
            "source": news_detail.source,
            "sourceUrl": news_detail.source_url,
            "hotScore": news_detail.hot_score or 0,
            "publishTime": news_detail.publish_time,
            "categoryId": news_detail.category_id,
            "views": news_detail.views,
            "relatedNews": related_news,
        },
    }


# ------------------------- 手动刷新 -------------------------
async def _run_refresh(per_feed: int, hot_limit: int, enable_hot: bool) -> None:
    _refresh_state.update({"status": "running", "startedAt": datetime.now().strftime("%H:%M:%S"),
                           "finishedAt": None, "added": 0, "message": "", "result": None})
    try:
        async with AsyncSessionLocal() as db:
            result = await collectors.refresh_all(db, per_feed=per_feed, hot_limit=hot_limit,
                                                  enable_hot=enable_hot)
        _refresh_state.update({
            "status": "done",
            "finishedAt": result["finishedAt"],
            "added": result["totalCreated"],
            "result": result,
            "message": f"新增 {result['totalCreated']} 条",
        })
        logger.info("手动刷新完成：%s", result)
    except Exception as exc:  # 采集失败不影响已有数据
        logger.exception("手动刷新失败")
        _refresh_state.update({"status": "error", "message": str(exc),
                               "finishedAt": datetime.now().strftime("%H:%M:%S")})


@router.post("/refresh")
async def refresh_news(
    per_feed: int = Query(default=settings.collect_per_feed, ge=1, le=40, description="每个 RSS 源抓取条数"),
    hot_limit: int = Query(default=settings.collect_hot_limit, ge=0, le=50, description="热搜条数，0 表示不抓"),
):
    """手动触发一次采集。立即返回，前端轮询 /refresh/status 获取进度。"""
    global _refresh_task, _last_refresh_ts

    if _refresh_state["status"] == "running":
        return {"code": 409, "message": "正在更新中，请稍候", "data": dict(_refresh_state)}

    elapsed = time.time() - _last_refresh_ts
    if _last_refresh_ts and elapsed < REFRESH_COOLDOWN:
        wait = int(REFRESH_COOLDOWN - elapsed)
        return {"code": 429, "message": f"刚刚更新过，请 {wait} 秒后再试", "data": {"wait": wait}}

    _last_refresh_ts = time.time()
    _refresh_task = asyncio.create_task(_run_refresh(per_feed, hot_limit, hot_limit > 0))
    return {"code": 200, "message": "已开始更新", "data": {"status": "running"}}


@router.get("/refresh/status")
async def refresh_status():
    return {"code": 200, "data": dict(_refresh_state)}


@router.get("/updated-at")
async def updated_at(db: AsyncSession = Depends(get_db)):
    latest, live_count = (await db.execute(
        select(func.max(News.fetched_at), func.count(News.id)).where(News.source != "seed")
    )).one()
    total = (await db.execute(select(func.count(News.id)))).scalar_one()
    return {
        "code": 200,
        "data": {
            "updatedAt": latest.strftime("%Y-%m-%d %H:%M:%S") if latest else None,
            "liveCount": int(live_count or 0),
            "totalCount": int(total or 0),
        },
    }
