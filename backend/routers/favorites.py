# 收藏模块路由
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from config.db_conf import get_db
from crud import favorites
from models.users import User
from schemas.favorites import FavoriteRequest
from utils.auth import get_current_user

router = APIRouter(prefix="/api/favorite", tags=["favorites"])


@router.get("/check")
async def check_favorite(
    news_id: int = Query(default=..., alias="newsId"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """检查新闻是否已被收藏"""
    is_favorite = await favorites.check_favorite(db, current_user.id, news_id)
    return {
        "code": 200,
        "message": "success",
        "data": {
            "isFavorite": is_favorite
        }
    }


@router.post("/add")
async def add_favorite(
    req: FavoriteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """添加收藏"""
    # 检查是否已收藏
    is_favorite = await favorites.check_favorite(db, current_user.id, req.newsId)
    if is_favorite:
        return {
            "code": 400,
            "message": "已收藏过该新闻",
            "data": None
        }

    favorite = await favorites.add_favorite(db, current_user.id, req.newsId)
    return {
        "code": 200,
        "message": "收藏成功",
        "data": {
            "id": favorite.id,
            "userId": favorite.user_id,
            "newsId": favorite.news_id,
            "createTime": favorite.created_at.isoformat() if favorite.created_at else None,
        }
    }


@router.delete("/remove")
async def remove_favorite(
    news_id: int = Query(default=..., alias="newsId"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """取消收藏"""
    success = await favorites.remove_favorite(db, current_user.id, news_id)
    if not success:
        return {
            "code": 404,
            "message": "收藏记录不存在",
            "data": None
        }

    return {
        "code": 200,
        "message": "取消收藏成功",
        "data": None
    }


@router.get("/list")
async def get_favorite_list(
    page: int = 1,
    page_size: int = Query(default=10, alias="pageSize", le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取收藏列表"""
    result = await favorites.get_favorite_list(db, current_user.id, page, page_size)
    return {
        "code": 200,
        "message": "success",
        "data": result
    }


@router.delete("/clear")
async def clear_favorites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """清空所有收藏"""
    count = await favorites.clear_favorites(db, current_user.id)
    return {
        "code": 200,
        "message": f"成功删除{count}条收藏记录",
        "data": None
    }
