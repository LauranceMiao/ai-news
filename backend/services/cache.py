"""进程内 TTL + LRU 缓存（无 Redis 依赖；后续可替换为 Redis 实现）。"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Optional

from config.settings import settings


class TTLCache:
    def __init__(self, max_items: int = 512, ttl: int = 3600) -> None:
        self.max_items = max_items
        self.ttl = ttl
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        item = self._data.get(key)
        if not item:
            self.misses += 1
            return None
        ts, value = item
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            self.misses += 1
            return None
        self._data.move_to_end(key)
        self.hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "size": len(self._data),
            "hits": self.hits,
            "misses": self.misses,
            "hitRate": round(self.hits / total, 3) if total else 0.0,
        }


cache = TTLCache(max_items=settings.cache_max_items, ttl=settings.cache_ttl)
