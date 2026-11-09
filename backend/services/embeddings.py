"""本地向量化：fastembed + bge-small-zh-v1.5（CPU 可跑，无需外部 API）。"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Iterable, Optional

import numpy as np

from config.settings import settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    pass


class Embedder:
    """懒加载的单例向量模型。

    首次调用会从 HuggingFace 镜像下载模型（约 100MB），之后走本地缓存。
    """

    def __init__(self) -> None:
        self._model = None
        self.dim = settings.embedding_dim

    def _ensure_env(self) -> None:
        if settings.hf_endpoint:
            os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
        settings.embedding_path.mkdir(parents=True, exist_ok=True)

    def _load(self):
        if self._model is not None:
            return self._model
        self._ensure_env()
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover
            raise EmbeddingError("未安装 fastembed，请执行 pip install fastembed") from exc

        logger.info("正在加载向量模型 %s（首次会下载）...", settings.embedding_model)
        try:
            self._model = TextEmbedding(
                model_name=settings.embedding_model,
                cache_dir=str(settings.embedding_path),
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:  # pragma: no cover - 依赖网络
            raise EmbeddingError(
                f"向量模型加载失败：{exc}。可检查网络，或设置 HF_ENDPOINT=https://hf-mirror.com"
            ) from exc
        return self._model

    @staticmethod
    def _normalize(matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    def embed_sync(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vectors = np.array(list(model.embed(texts)), dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        self.dim = int(vectors.shape[1])
        return self._normalize(vectors)

    async def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return await asyncio.to_thread(self.embed_sync, texts)

    async def embed_one(self, text: str) -> np.ndarray:
        vectors = await self.embed([text])
        return vectors[0]


embedder = Embedder()
