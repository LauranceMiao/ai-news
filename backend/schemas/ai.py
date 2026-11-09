"""AI 接口的请求/响应模型。"""
from typing import Optional

from pydantic import BaseModel, Field


class SummaryRequest(BaseModel):
    newsId: int = Field(..., description="新闻ID")
    force: bool = Field(False, description="忽略缓存重新生成")


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="用户问题")
    sessionId: Optional[int] = Field(None, description="会话ID，为空则新建")
    newsId: Optional[int] = Field(None, description="限定在某篇新闻内提问")
    history: Optional[list[dict]] = Field(None, description="前端回传的上下文（可选）")


class RelatedQuery(BaseModel):
    newsId: int
    limit: int = 5
