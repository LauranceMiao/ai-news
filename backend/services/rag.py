"""RAG 核心：文本切分 → 向量化入库 → 余弦召回 → 组装 Prompt。"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
from sqlalchemy import delete, select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from models.ai import NewsChunk
from models.news import News
from services.cache import cache
from services.embeddings import embedder, EmbeddingError
from services.llm_client import estimate_tokens

logger = logging.getLogger(__name__)

SENTENCE_ENDS = "。！？!?；;\n"


@dataclass
class Chunk:
    index: int
    start: int
    end: int
    text: str


def split_text(content: str, size: Optional[int] = None, overlap: Optional[int] = None) -> list[Chunk]:
    """按句子边界切分，带重叠，避免把一句话切断。"""
    size = size or settings.rag_chunk_size
    overlap = overlap or settings.rag_chunk_overlap
    content = (content or "").strip()
    if not content:
        return []
    if len(content) <= size:
        return [Chunk(0, 0, len(content), content)]

    chunks: list[Chunk] = []
    start = 0
    idx = 0
    while start < len(content):
        end = min(start + size, len(content))
        if end < len(content):
            window_start = start + int(size * 0.6)
            window = content[window_start:end]
            cut = max(window.rfind(ch) for ch in SENTENCE_ENDS)
            if cut >= 0:
                end = window_start + cut + 1
        piece = content[start:end].strip()
        if piece:
            chunks.append(Chunk(idx, start, end, piece))
            idx += 1
        if end >= len(content):
            break
        start = max(end - overlap, start + 1)
    return chunks


# ------------------------- 向量索引 -------------------------
@dataclass
class VectorStore:
    matrix: np.ndarray
    chunk_ids: np.ndarray
    news_ids: np.ndarray
    contents: list[str]
    built_at: float


_store: Optional[VectorStore] = None
_store_version = 0
STORE_TTL = 300  # 秒，多进程时也能最终一致


def bump_version() -> None:
    global _store_version
    _store_version += 1


async def _load_store(db: AsyncSession) -> VectorStore:
    rows = (await db.execute(
        select(NewsChunk.id, NewsChunk.news_id, NewsChunk.content, NewsChunk.embedding)
        .where(NewsChunk.embedding.isnot(None))
    )).all()

    vectors, chunk_ids, news_ids, contents = [], [], [], []
    for chunk_id, news_id, content, blob in rows:
        if not blob:
            continue
        vec = np.frombuffer(blob, dtype=np.float32)
        vectors.append(vec)
        chunk_ids.append(chunk_id)
        news_ids.append(news_id)
        contents.append(content)

    if not vectors:
        dim = settings.embedding_dim
        return VectorStore(np.zeros((0, dim), np.float32), np.array([], dtype=np.int64),
                           np.array([], dtype=np.int64), [], time.time())

    matrix = np.vstack(vectors).astype(np.float32)
    return VectorStore(matrix, np.array(chunk_ids), np.array(news_ids), contents, time.time())


async def get_store(db: AsyncSession) -> VectorStore:
    global _store
    if _store is None or _store_version or (time.time() - _store.built_at > STORE_TTL):
        _store = await _load_store(db)
        globals()["_store_version"] = 0
    return _store


async def index_news(db: AsyncSession, news_ids: Optional[list[int]] = None,
                     force: bool = False, batch_size: int = 64) -> dict:
    """对新闻建切片索引；news_ids 为空表示全量。"""
    stmt = select(News.id, News.title, News.description, News.content)
    if news_ids:
        stmt = stmt.where(News.id.in_(news_ids))
    rows = (await db.execute(stmt)).all()

    indexed = 0
    skipped = 0
    total_chunks = 0
    for news_id, title, description, content in rows:
        if not force:
            exists = (await db.execute(
                select(NewsChunk.id).where(NewsChunk.news_id == news_id).limit(1)
            )).scalar_one_or_none()
            if exists:
                skipped += 1
                continue

        body = (content or "").strip()
        head = f"【{title}】{description or ''}".strip()
        chunks = split_text(head + "\n" + body)
        if not chunks:
            skipped += 1
            continue

        await db.execute(delete(NewsChunk).where(NewsChunk.news_id == news_id))

        vectors: list[np.ndarray] = []
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            vecs = await embedder.embed([c.text for c in batch])
            vectors.extend(list(vecs))

        for chunk, vec in zip(chunks, vectors):
            db.add(NewsChunk(
                news_id=news_id,
                chunk_index=chunk.index,
                content=chunk.text,
                char_start=chunk.start,
                char_end=chunk.end,
                token_count=estimate_tokens(chunk.text),
                embedding=vec.astype(np.float32).tobytes(),
                dim=int(vec.shape[0]),
            ))
        await db.commit()
        indexed += 1
        total_chunks += len(chunks)

    bump_version()
    return {"news": len(rows), "indexed": indexed, "skipped": skipped, "chunks": total_chunks}


# ------------------------- 检索 -------------------------
async def search(db: AsyncSession, query: str, top_k: Optional[int] = None,
                 news_id: Optional[int] = None, min_score: Optional[float] = None) -> list[dict]:
    top_k = top_k or settings.rag_top_k
    min_score = settings.rag_min_score if min_score is None else min_score

    cache_key = f"search:{news_id}:{top_k}:{query.strip()[:120]}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    store = await get_store(db)
    if store.matrix.shape[0] == 0:
        return []

    qv = await embedder.embed_one(query)
    scores = store.matrix @ qv

    if news_id:
        mask = store.news_ids != news_id
        scores = np.where(mask, -1.0, scores)

    order = np.argsort(-scores)[: max(top_k * 4, top_k)]
    best_per_news: dict[int, int] = {}
    for pos in order:
        score = float(scores[pos])
        if score < min_score:
            break
        nid = int(store.news_ids[pos])
        if nid not in best_per_news:
            best_per_news[nid] = pos
        if len(best_per_news) >= top_k * 3:
            break

    if not best_per_news:
        return []

    rows = (await db.execute(
        select(News.id, News.title, News.description, News.image, News.publish_time, News.author)
        .where(News.id.in_(best_per_news.keys()))
    )).all()
    news_map = {r.id: r for r in rows}

    hits = []
    seen_titles: set[str] = set()
    for nid, pos in best_per_news.items():
        news = news_map.get(nid)
        if not news:
            continue
        title_key = (news.title or "").strip()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        hits.append({
            "newsId": nid,
            "title": news.title,
            "content": store.contents[pos],
            "score": round(float(scores[pos]), 4),
            "description": news.description,
            "image": news.image,
            "author": news.author,
            "publishTime": news.publish_time.strftime("%Y-%m-%d %H:%M") if news.publish_time else None,
        })
    hits.sort(key=lambda h: -h["score"])
    hits = hits[:top_k]
    cache.set(cache_key, hits)
    return hits


def build_context(hits: list[dict], max_chars: int = 4000) -> str:
    """把召回结果拼成带编号、带发布时间的上下文，供模型判断新旧。"""
    lines = []
    used = 0
    for i, hit in enumerate(hits, 1):
        published = hit.get("publishTime") or "未知时间"
        piece = f"[{i}] 《{hit['title']}》（发布于 {published}）\n{hit['content']}\n"
        if used + len(piece) > max_chars:
            break
        lines.append(piece)
        used += len(piece)
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "你是一个中文新闻问答助手。请严格依据提供的新闻资料回答用户问题，要求：\n"
    "1. 只使用资料中的信息，资料没有的内容不要编造；确实没有就说明“资料中未提及”。\n"
    "2. 引用资料时用 [1][2] 这样的编号标注，编号对应资料序号。\n"
    "3. 每条资料都带发布日期：用户问“最新/最近”时，优先采用日期最新的资料，并在回答里说明具体日期。\n"
    "4. 如果资料都比较旧，要明确提醒用户“目前站内最新的是 X 月 X 日的内容”。\n"
    "5. 回答用中文，分点清晰，200 字以内，不要重复题目。"
)


def build_messages(question: str, hits: list[dict], history: Optional[list[dict]] = None) -> list[dict]:
    context = build_context(hits)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in (history or [])[-6:]:
        if item.get("role") in ("user", "assistant") and item.get("content"):
            messages.append({"role": item["role"], "content": item["content"][:800]})
    user_content = f"参考资料：\n{context}\n\n用户问题：{question}" if context else f"用户问题：{question}"
    messages.append({"role": "user", "content": user_content})
    return messages
