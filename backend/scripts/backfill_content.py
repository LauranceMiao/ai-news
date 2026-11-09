"""回填正文：把「只有几十字摘要」的历史新闻重新回源站抓全文和配图。

用法：
    python -m scripts.backfill_content            # 处理所有短正文新闻
    python -m scripts.backfill_content --limit 30 # 先试 30 条
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from config.db_conf import AsyncSessionLocal  # noqa: E402
from models.news import News  # noqa: E402
from services.article import fetch_article  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--threshold", type=int, default=300, help="正文短于多少字才回填")
    parser.add_argument("--force", action="store_true", help="不管长短都重抓（用于清洗旧正文）")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        stmt = (select(News)
                .where(News.source_url.isnot(None))
                .order_by(News.id.desc()))
        rows = (await db.execute(stmt)).scalars().all()
        targets = rows if args.force else [n for n in rows if len(n.content or "") < args.threshold]
        if args.limit:
            targets = targets[: args.limit]

        print(f"待回填 {len(targets)} 条（总 {len(rows)} 条）")
        sem = asyncio.Semaphore(5)
        done = 0
        improved = 0

        async def handle(news: News) -> None:
            nonlocal done, improved
            async with sem:
                article = await fetch_article(news.source_url)
            done += 1
            if not article:
                return
            if args.force or len(article["content"]) > len(news.content or "") + 80:
                news.content = article["content"]
                news.description = article["content"][:480]
                if article.get("image"):
                    news.image = article["image"]
                improved += 1
            if done % 20 == 0:
                print(f"  进度 {done}/{len(targets)}，已更新 {improved}")

        await asyncio.gather(*(handle(n) for n in targets), return_exceptions=True)
        await db.commit()
        print(f"完成：处理 {done} 条，更新 {improved} 条")


if __name__ == "__main__":
    asyncio.run(main())
