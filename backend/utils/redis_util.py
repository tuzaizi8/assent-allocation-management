"""Redis 工具类。

提供 Redis 连接池的创建、检测、关闭功能。
使用 redis.asyncio 异步客户端，在 lifespan 中初始化并挂载到 app.state.redis。
"""

from fastapi import FastAPI
from redis import asyncio as aioredis
from redis.exceptions import AuthenticationError, RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from config.settings import RedisConfig
from utils.log import logger


class RedisUtil:
    """Redis 连接管理工具类。"""

    @classmethod
    async def create_redis_pool(cls) -> aioredis.Redis:
        """应用启动时创建 Redis 连接。

        使用 redis.asyncio.from_url 创建异步连接客户端，
        内部基于连接池实现，多次 get/set 复用同一连接池。

        :return: Redis 连接对象
        """
        logger.info('🔎 开始连接 Redis...')
        redis = await aioredis.from_url(
            url=f'redis://{RedisConfig.redis_host}',
            port=RedisConfig.redis_port,
            username=RedisConfig.redis_username,
            password=RedisConfig.redis_password,
            db=RedisConfig.redis_database,
            encoding='utf-8',
            decode_responses=True,
        )
        await cls.check_redis_connection(redis)
        return redis

    @classmethod
    async def check_redis_connection(cls, redis: aioredis.Redis) -> None:
        """检查 Redis 连接状态。

        通过 PING 命令探测连接是否正常，并按异常类型输出不同日志。

        :param redis: Redis 连接对象
        :return: None
        """
        try:
            connection = await redis.ping()
            if connection:
                logger.info('✅️ Redis 连接成功')
            else:
                logger.error('❌️ Redis 连接失败')
        except AuthenticationError as e:
            logger.error(f'❌️ Redis 用户名或密码错误：{e}')
        except RedisTimeoutError as e:
            logger.error(f'❌️ Redis 连接超时：{e}')
        except RedisError as e:
            logger.error(f'❌️ Redis 连接错误：{e}')

    @classmethod
    async def close_redis_pool(cls, app: FastAPI) -> None:
        """应用关闭时关闭 Redis 连接。

        :param app: FastAPI 应用对象，从中取出 app.state.redis
        :return: None
        """
        await app.state.redis.close()
        logger.info('✅️ 关闭 Redis 连接成功')