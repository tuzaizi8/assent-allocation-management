"""
- 异步 Engine + 连接池
- async_sessionmaker 会话工厂
- Base 声明式基类（AsyncAttrs + DeclarativeBase）
"""
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config.settings import DataBaseConfig

# 创建异步引擎（全局单例）
async_engine: AsyncEngine = create_async_engine(
    DataBaseConfig.async_url,
    echo=DataBaseConfig.db_echo,
    pool_size=DataBaseConfig.db_pool_size,
    max_overflow=DataBaseConfig.db_max_overflow,
    pool_recycle=DataBaseConfig.db_pool_recycle,
    pool_timeout=DataBaseConfig.db_pool_timeout,
)

# 创建异步会话工厂（全局单例）
# expire_on_commit=False：多数读路径会在请求中途 commit（净值回源、待确认交易回填）后继续使用
# 先前查出的 ORM 对象；默认的 commit 后过期策略会让这些属性访问触发同步 refresh，
# 在 async 上下文里直接抛 MissingGreenlet（表现为冷缓存首访 500、刷新即好）
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(AsyncAttrs, DeclarativeBase):
    """所有 ORM 模型的基类

    继承 AsyncAttrs：支持异步属性加载（relationship 等需要 await）
    继承 DeclarativeBase：SQLAlchemy 2.0 声明式基类
    """
    pass