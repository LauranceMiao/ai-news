# 收藏相关校验模型
from typing import Optional

from pydantic import BaseModel


class FavoriteRequest(BaseModel):
    newsId: int


class FavoriteNewsItem(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    image: Optional[str] = None
    author: Optional[str] = None
    publishTime: Optional[str] = None
    categoryId: int
    views: int
    favoriteTime: Optional[str] = None
