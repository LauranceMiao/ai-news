# 浏览历史相关校验模型
from typing import Optional

from pydantic import BaseModel


class HistoryRequest(BaseModel):
    newsId: int


class HistoryNewsItem(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    image: Optional[str] = None
    author: Optional[str] = None
    publishTime: Optional[str] = None
    categoryId: int
    views: int
    viewTime: Optional[str] = None
