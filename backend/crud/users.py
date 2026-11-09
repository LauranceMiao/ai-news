"""用户相关的数据库操作：查询、创建、登录验证（JWT）。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.users import User
from schemas.users import UserRequest
from utils import security
from utils.auth import create_access_token


async def get_user_by_username(db: AsyncSession, username: str):
    query = select(User).where(User.username == username)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, user_data: UserRequest):
    hashed_password = security.get_hash_password(user_data.password)
    user = User(username=user_data.username, password=hashed_password)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login_user(db: AsyncSession, username: str, password: str):
    """校验用户名密码，返回 (user, jwt_token)。"""
    user = await get_user_by_username(db, username)
    if not user:
        return None, None
    if not security.verify_password(password, user.password):
        return None, None
    token = create_access_token(user.id, user.username)
    return user, token
