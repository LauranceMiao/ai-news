# 浏览历史模块路由
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from config.db_conf import get_db
from crud import history
from models.users import User
from schemas.history import HistoryRequest
from utils.auth import get_current_user

router = APIRouter(prefix="/api/history", tags=["history"])


@router.post("/add")
async def add_history(
    req: HistoryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """添加浏览记录"""
    record = await history.add_history(db, current_user.id, req.newsId)
    return {
        "code": 200,
        "message": "添加成功",
        "data": {
            "id": record.id,
            "userId": record.user_id,
            "newsId": record.news_id,
            "viewTime": record.view_time.isoformat() if record.view_time else None,
        }
    }


@router.get("/list")
async def get_history_list(
    page: int = 1,
    page_size: int = Query(default=10, alias="pageSize", le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取浏览历史列表"""
    result = await history.get_history_list(db, current_user.id, page, page_size)
    return {
        "code": 200,
        "message": "success",
        "data": result
    }


@router.delete("/delete/{history_id}")
async def delete_history(
    history_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除单条浏览记录"""
    success = await history.delete_history(db, current_user.id, history_id)
    if not success:
        return {
            "code": 404,
            "message": "历史记录不存在",
            "data": None
        }

    return {
        "code": 200,
        "message": "删除成功",
        "data": None
    }


@router.delete("/clear")
async def clear_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """清空浏览历史"""
    count = await history.clear_history(db, current_user.id)
    return {
        "code": 200,
        "message": f"清空成功",
        "data": None
    }
