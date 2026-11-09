"""CLI：为新闻建立向量索引。

用法：
    python -m scripts.build_index            # 增量（只处理还没索引的新闻）
    python -m scripts.build_index --force    # 全量重建
    python -m scripts.build_index --limit 50 # 只处理前 50 条，方便先试跑
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from config.db_conf import AsyncSessionLocal  # noqa: E402
from models.news import News  # noqa: E402
from services import rag  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="全量重建")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        total = (await db.execute(select(func.count(News.id)))).scalar_one()
        print(f"新闻总数：{total}")

        news_ids = None
        if args.limit:
            news_ids = list((await db.execute(
                select(News.id).order_by(News.id.desc()).limit(args.limit)
            )).scalars().all())

        result = await rag.index_news(db, news_ids, force=args.force)
        print(f"完成：{result}")


if __name__ == "__main__":
    asyncio.run(main())
