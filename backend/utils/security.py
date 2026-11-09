#utils：工具

from passlib.context import CryptContext

#创建密码上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


#密码加密方法
def get_hash_password(password: str):
    return pwd_context.hash(password)


#密码验证方法
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)