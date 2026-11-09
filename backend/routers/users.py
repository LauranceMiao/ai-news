"""用户注册 / 登录 / 资料（JWT 版）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.db_conf import get_db
from crud import users
from models.users import User
from schemas.users import UserRequest
from utils.auth import create_access_token, get_current_user

router = APIRouter(prefix="/api/user", tags=["users"])


@router.post("/register")
async def register(user_data: UserRequest, db: AsyncSession = Depends(get_db)):
    existing_user = await users.get_user_by_username(db, user_data.username)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该用户已存在")

    user = await users.create_user(db, user_data)
    token = create_access_token(user.id, user.username)

    return {
        "code": 200,
        "message": "注册成功",
        "data": {
            "token": token,
            "userInfo": {
                "id": user.id,
                "username": user.username,
                "bio": user.bio,
                "avatar": user.avatar,
            },
        },
    }


@router.post("/login")
async def login(user_data: UserRequest, db: AsyncSession = Depends(get_db)):
    user, token = await users.login_user(db, user_data.username, user_data.password)
    if not user:
        return {"code": 401, "message": "用户名或密码错误", "data": None}

    return {
        "code": 200,
        "message": "登录成功",
        "data": {
            "token": token,
            "tokenType": "Bearer",
            "userInfo": {
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "avatar": user.avatar,
                "bio": user.bio,
            },
        },
    }


@router.get("/profile")
async def profile(user: User = Depends(get_current_user)):
    """演示 JWT 鉴权：带上 Authorization: Bearer <token> 即可拿到当前用户。"""
    return {
        "code": 200,
        "data": {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "avatar": user.avatar,
            "bio": user.bio,
        },
    }
