"""数据库依赖注入 + 生命周期钩子"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal, Base, async_engine
from utils.log import logger


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """数据库依赖注入

    每个请求独立一个 Session，请求结束自动关闭。

    用法：
        from fastapi import Depends
        @router.get('/users')
        async def list_users(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(User))
            return result.scalars().all()
    """
    async with AsyncSessionLocal() as current_db:
        yield current_db


async def init_create_table() -> None:
    """应用启动时初始化数据库表

    在 lifespan 启动阶段调用，自动创建所有继承 Base 的模型对应的表。
    已存在的表不会被修改（需用 Alembic 做迁移）。
    """
    logger.info('🔎 初始化数据库连接...')
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info('✅ 数据库连接成功，表结构初始化完成')


async def close_async_engine() -> None:
    """应用关闭时释放连接池

    在 lifespan 关闭阶段调用，释放所有数据库连接。
    """
    logger.info('🔌 关闭数据库连接池...')
    await async_engine.dispose()
    logger.info('✅ 数据库连接池已关闭')