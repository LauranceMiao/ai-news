"""全局配置：统一从 .env 读取，避免密钥硬编码。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 应用
    app_name: str = "AI 新闻聚合与问答系统"
    debug: bool = True

    # 数据库
    db_url: str = "mysql+aiomysql://root:password@127.0.0.1:3306/news_ai?charset=utf8mb4"
    db_echo: bool = False

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model_fast: str = "deepseek-flash"
    deepseek_model_pro: str = "deepseek-v4-pro"
    llm_timeout: float = 120.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.3
    llm_send_effort: bool = False
    llm_effort: str = "low"

    price_in_fast: float = 0.5
    price_out_fast: float = 2.0
    price_in_pro: float = 2.0
    price_out_pro: float = 8.0

    # JWT
    jwt_secret: str = "dev-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # 向量检索
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dim: int = 512
    embedding_cache_dir: str = ".cache/fastembed"
    hf_endpoint: str = "https://hf-mirror.com"
    rag_top_k: int = 6
    rag_chunk_size: int = 300
    rag_chunk_overlap: int = 60
    rag_min_score: float = 0.30

    # 采集（手动触发）
    collect_per_feed: int = 15
    collect_hot_limit: int = 20
    keep_per_source: int = 200
    keep_max_rows: int = 5000
    refresh_cooldown: int = 60
    # 只收最近 N 天的新闻，RSS 里的陈年旧闻直接丢掉
    max_news_age_days: int = 7

    # 缓存
    cache_ttl: int = 3600
    cache_max_items: int = 512

    @property
    def embedding_path(self) -> Path:
        p = Path(self.embedding_cache_dir)
        return p if p.is_absolute() else BASE_DIR / p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
