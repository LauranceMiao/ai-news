"""手动刷新采集：百度热搜 + RSS 新闻源。

设计要点：
- 只有用户点「刷新」时才抓，不做后台定时；
- 抓到的新闻按来源打标（source），seed 数据保留作兜底；
- 入库后只对新新闻建向量索引，热搜类不建（只有标题，进 RAG 会污染答案）；
- 每次刷新后按保留策略清理，库不会无限膨胀。
"""
from __future__ import annotations

import asyncio
import calendar
import html
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import feedparser
import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from models.news import News
from services import rag
from services.article import fetch_article
logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.I)

# 分类 id：1头条 2社会 3国内 4国际 5娱乐 6体育 7科技 8财经
RSS_FEEDS = [
    {"name": "中新网", "url": "https://www.chinanews.com.cn/rss/scroll-news.xml", "category": 1},
    {"name": "中新网-社会", "url": "https://www.chinanews.com.cn/rss/society.xml", "category": 2},
    {"name": "中新网-国际", "url": "https://www.chinanews.com.cn/rss/world.xml", "category": 4},
    {"name": "中新网-文化", "url": "https://www.chinanews.com.cn/rss/culture.xml", "category": 5},
    {"name": "中新网-体育", "url": "https://www.chinanews.com.cn/rss/sports.xml", "category": 6},
    {"name": "中新网-财经", "url": "https://www.chinanews.com.cn/rss/finance.xml", "category": 8},
    {"name": "中新网-国内", "url": "https://www.chinanews.com.cn/rss/china.xml", "category": 3},
    {"name": "IT之家", "url": "https://www.ithome.com/rss/", "category": 7},
    {"name": "爱范儿", "url": "https://www.ifanr.com/feed", "category": 7},
    {"name": "Solidot", "url": "https://www.solidot.org/index.rss", "category": 7},
    {"name": "少数派", "url": "https://sspai.com/feed", "category": 7},
]

# 关键词 → 分类，按顺序匹配（越具体越靠前）
CATEGORY_RULES = [
    (5, ("明星", "电影", "电视剧", "综艺", "演员", "歌手", "演唱会", "票房", "导演", "主演", "热播")),
    (6, ("比赛", "球队", "球员", "联赛", "冠军", "奥运", "世界杯", "篮球", "足球", "夺冠", "三分", "赛事")),
    (8, ("股市", "基金", "房价", "经济", "GDP", "央行", "利率", "上市", "融资", "市值", "财报", "消费", "行业")),
    (7, ("手机", "iPhone", "芯片", "AI", "大模型", "苹果", "华为", "发布会", "机器人", "卫星", "火箭",
         "量子", "电动车", "特斯拉", "科技", "算法", "开源")),
    (4, ("美国", "俄罗斯", "乌克兰", "日本", "韩国", "欧洲", "联合国", "以色列", "伊朗", "特朗普",
         "外交", "外长", "总统", "首相")),
    (2, ("事故", "警方", "通报", "起火", "坠楼", "失联", "救援", "法院", "判决", "村民", "小区",
         "外卖", "女子", "男子", "老人", "孩子")),
]

BAIDU_HOT_URL = "https://top.baidu.com/api/board?platform=wise&tab=realtime"


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    text = TAG_RE.sub("\n", raw)
    text = html.unescape(text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())



def guess_category(title: str, default: int = 1) -> int:
    for category_id, words in CATEGORY_RULES:
        if any(word in title for word in words):
            return category_id
    return default


def extract_image(entry: dict, raw_html: str) -> Optional[str]:
    for key in ("media_content", "media_thumbnail"):
        for item in entry.get(key) or []:
            if item.get("url"):
                return item["url"]
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
            return link.get("href")
    match = IMG_RE.search(raw_html or "")
    return match.group(1) if match else None


def parse_published(entry: dict) -> datetime:
    """RSS 的 published_parsed 是 UTC，这里转成本地时间。"""
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromtimestamp(calendar.timegm(value))
            except (TypeError, ValueError, OverflowError):
                continue
    return datetime.now()


async def _title_exists(db: AsyncSession, title: str) -> bool:
    stmt = select(News.id).where(News.title == title).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def collect_rss(db: AsyncSession, per_feed: int = 15) -> dict:
    """抓取 RSS 源：先收元数据，再对「摘要太短」的条目回源站抓正文，最后统一入库。"""
    created, new_ids, errors = 0, [], []
    candidates: list[dict] = []

    async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True, timeout=20) as client:
        for feed_conf in RSS_FEEDS:
            try:
                resp = await client.get(feed_conf["url"])
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
            except Exception as exc:
                errors.append(f"{feed_conf['name']}: {exc}")
                continue

            for entry in feed.entries[:per_feed]:
                title = (entry.get("title") or "").strip()
                if not title or await _title_exists(db, title):
                    continue

                published = parse_published(entry)
                # RSS 里经常混着几年前的老文章（有的源干脆停更了），只收最近 N 天
                if published < datetime.now() - timedelta(days=settings.max_news_age_days):
                    continue

                raw_html = ""
                if entry.get("content"):
                    raw_html = entry["content"][0].get("value", "")
                if not raw_html:
                    raw_html = entry.get("summary", "") or entry.get("description", "")
                body = html_to_text(raw_html)

                candidates.append({
                    "feed": feed_conf,
                    "title": title,
                    "published": published,
                    "body": body,
                    "image": extract_image(entry, raw_html),
                    "link": (entry.get("link") or "").strip(),
                    "author": (entry.get("author") or feed_conf["name"])[:50],
                })

    # 摘要太短的，并发回源站抓正文（限 5 并发，失败就保留原摘要）
    need_full = [c for c in candidates if len(c["body"]) < 200 and c["link"]]
    if need_full:
        sem = asyncio.Semaphore(5)

        async def enrich(item: dict) -> None:
            async with sem:
                article = await fetch_article(item["link"])
            if not article:
                return
            if len(article["content"]) > len(item["body"]):
                item["body"] = article["content"]
            if article.get("image"):
                item["image"] = article["image"]

        await asyncio.gather(*(enrich(c) for c in need_full), return_exceptions=True)

    for item in candidates:
        body = (item["body"] or "").strip()
        if len(body) < 40:
            body = f"{item['title']}（原文内容暂不可用，点击原文查看）"

        news = News(
            title=item["title"][:255],
            description=body[:480],
            content=body,
            image=item["image"],
            author=item["author"],
            category_id=guess_category(item["title"], item["feed"]["category"]),
            publish_time=item["published"],
            source=item["feed"]["name"],
            source_url=item["link"][:500] or None,
            hot_score=0,
            fetched_at=datetime.now(),
        )
        db.add(news)
        await db.flush()
        new_ids.append(news.id)
        created += 1

    await db.commit()
    return {"created": created, "ids": new_ids, "errors": errors}


async def collect_baidu_hot(db: AsyncSession, limit: int = 20) -> dict:
    """抓百度热搜榜，只有标题+热度，不入向量索引。"""
    created, errors = 0, []
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=15) as client:
            resp = await client.get(BAIDU_HOT_URL)
            resp.raise_for_status()
            data = resp.json()
        items = data["data"]["cards"][0]["content"][0]["content"]
    except Exception as exc:
        return {"created": 0, "errors": [f"百度热搜: {exc}"]}

    for index, item in enumerate(items[:limit]):
        word = (item.get("word") or "").strip()
        if not word:
            continue
        title = f"热搜：{word}"
        if await _title_exists(db, title):
            continue
        url = item.get("url") or ""
        tag = item.get("labelTagName") or ""
        hot = max(1, 100 - index * 2)
        db.add(News(
            title=title[:255],
            description=f"百度热搜话题（热度 {hot}）{'· ' + tag if tag else ''}",
            content=f"百度热搜话题：{word}\n\n热度值：{hot}\n话题标签：{tag or '无'}\n"
                    f"说明：该条目为热搜话题，正文请点击原文链接查看。\n原文链接：{url}",
            image=None,
            author="百度热搜",
            category_id=guess_category(word, 1),
            publish_time=datetime.now(),
            source="baidu_hot",
            source_url=url[:500] or None,
            hot_score=hot,
            fetched_at=datetime.now(),
        ))
        created += 1
    await db.commit()
    return {"created": created, "errors": errors}


async def apply_retention(db: AsyncSession, per_source: Optional[int] = None,
                          max_rows: Optional[int] = None) -> dict:
    """保留策略：每个来源只留最新 N 条；非 seed 总量超上限时按时间删除。"""
    per_source = per_source or settings.keep_per_source
    max_rows = max_rows or settings.keep_max_rows
    removed = 0
    sources = (await db.execute(
        select(News.source).where(News.source != "seed").distinct()
    )).scalars().all()

    for source in sources:
        ids = (await db.execute(
            select(News.id).where(News.source == source).order_by(News.id.desc()).offset(per_source)
        )).scalars().all()
        if ids:
            await db.execute(delete(News).where(News.id.in_(ids)))
            removed += len(ids)

    total = (await db.execute(
        select(func.count(News.id)).where(News.source != "seed")
    )).scalar_one()
    if total > max_rows:
        ids = (await db.execute(
            select(News.id).where(News.source != "seed").order_by(News.id.desc()).offset(max_rows)
        )).scalars().all()
        if ids:
            await db.execute(delete(News).where(News.id.in_(ids)))
            removed += len(ids)

    # 清掉没有任何切片的孤儿切片（删除新闻时外键已级联，这里兜底）
    if removed:
        await db.commit()
        rag.bump_version()
    return {"removed": removed}


async def refresh_all(db: AsyncSession, per_feed: Optional[int] = None, hot_limit: Optional[int] = None,
                      enable_hot: bool = True) -> dict:
    """一次完整的手动刷新。"""
    per_feed = per_feed or settings.collect_per_feed
    hot_limit = settings.collect_hot_limit if hot_limit is None else hot_limit
    started = datetime.now()
    rss = await collect_rss(db, per_feed)
    hot = await collect_baidu_hot(db, hot_limit) if enable_hot else {"created": 0, "errors": []}

    # 热搜/短文本不进索引，只给 RSS 新新闻建
    indexed = None
    if rss["ids"]:
        try:
            indexed = await rag.index_news(db, rss["ids"])
        except Exception as exc:  # 向量模型异常不应导致整次刷新失败
            logger.warning("建索引失败：%s", exc)

    retention = await apply_retention(db)

    return {
        "startedAt": started.strftime("%H:%M:%S"),
        "finishedAt": datetime.now().strftime("%H:%M:%S"),
        "rssCreated": rss["created"],
        "hotCreated": hot["created"],
        "totalCreated": rss["created"] + hot["created"],
        "indexed": indexed,
        "removed": retention["removed"],
        "errors": rss["errors"] + hot["errors"],
    }
