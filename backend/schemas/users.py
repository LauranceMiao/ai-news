#进行类型校验，用 Pydantic 定义请求体和响应体的数据结构，做自动校验和文档生成

from typing import Optional

from pydantic import BaseModel   #请求体参数


class UserRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: int
    username: str
    bio: Optional[str] = None
    avatar: Optional[str] = None


class LoginResponse(BaseModel):
    code: int
    message: str
    data: Optional[dict] = None


