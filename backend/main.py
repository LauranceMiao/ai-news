"""AI 新闻聚合与问答系统 · FastAPI 入口。

采集策略：不做后台定时抓取，只提供手动刷新接口（/api/news/refresh），
避免库无限增长和不必要的向量化开销。
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from routers import ai, favorites, history, news, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("%s 启动完成（手动刷新模式）", settings.app_name)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(news.router)
app.include_router(users.router)
app.include_router(favorites.router)
app.include_router(history.router)
app.include_router(ai.router)


@app.get("/")
async def root():
    return {"message": settings.app_name, "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
