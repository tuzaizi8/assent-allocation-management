"""应用工厂与生命周期管理。

将配置、日志、数据库、响应封装、异常、中间件、上下文、安全、路由
全部组装到 FastAPI 应用中。
"""
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from config.settings import AppConfig
from db.get_db import close_async_engine, init_create_table
from db.init_data import init_seed_data
from utils.log import logger
from utils.redis_util import RedisUtil

from common.router import auto_register_routers
from exceptions.handle import handle_exception
from middlewares.handle import handle_middleware

from module_system.service.oper_log_service import consume_oper_log_queue

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理。

    启动阶段:初始化 Redis 连接池、数据库表结构、种子数据,启动操作日志后台消费任务。
    关闭阶段:停止日志消费任务,关闭 Redis 连接,释放数据库连接池。

    :param app: FastAPI 应用实例
    :return: 异步生成器,yield 前为启动逻辑,yield 后为关闭逻辑
    """
    # ========== 启动阶段 ==========
    logger.info(f'⏰️ {AppConfig.app_name} 开始启动')
    # 1. 初始化 Redis 连接（先于数据库，因为数据库会话可能用到 Redis 缓存）
    #    create_redis_pool 内部：from_url 不捕获异常（配置错误会中断启动），
    #    ping 被 check_redis_connection 吞掉（服务没启动不中断）
    try:
        app.state.redis = await RedisUtil.create_redis_pool()
    except Exception as e:
        # from_url 阶段的异常（URL 非法、网络完全不可达）会到这里
        logger.error(f"❌️ Redis 连接创建失败，应用无法启动：{e}")
        raise
    # 初始化数据库表（继承 Base 的所有模型对应的表）
    await init_create_table()
    # 初始化种子数据（sys_user 为空时创建种子管理员，保证首启可登录）
    await init_seed_data()
    # 操作日志后台消费任务(异步队列消费,不阻塞请求)
    app.state.oper_log_task = asyncio.create_task(consume_oper_log_queue())
    logger.info('🚀 应用启动完成，开始接收请求')

    yield  # <-- 应用运行期间，所有请求在此期间被处理

    # ========== 关闭阶段 ==========
    logger.info(f'🛑 {AppConfig.app_name} 开始关闭')
    # 先停日志消费任务(等待当前条目写完)
    app.state.oper_log_task.cancel()
    with suppress(asyncio.CancelledError):
        await app.state.oper_log_task
    # 1. 关闭 Redis 连接
    try:
        await RedisUtil.close_redis_pool(app)
    except Exception as e:
        logger.error(f"关闭 Redis 连接时出错：{e}")
    # 释放数据库连接池
    await close_async_engine()
    logger.info('✅ 应用已安全关闭')


def create_app() -> FastAPI:
    """应用工厂函数。

    按以下顺序组装 FastAPI 应用：
    1. 创建 FastAPI 实例（绑定 lifespan）
    2. 注册中间件链（CORS + Gzip + Trace + 上下文清理）
    3. 自动挂载路由（调用 RouterRegister）
    4. 注册全局异常处理器

    :return: 组装完成的 FastAPI 应用实例
    """
    # 1. 创建 FastAPI 实例，绑定生命周期管理器
    app = FastAPI(
        title=AppConfig.app_name,
        root_path=AppConfig.app_root_path,  # 网关前缀(.env.dev 已有 APP_ROOT_PATH=/api)
        description=f"{AppConfig.app_name} 接口文档",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 2. 注册中间件（注册顺序与执行顺序相反）
    handle_middleware(app)

    # 3. 自动挂载路由（扫描 */controller/[!_]*.py）
    auto_register_routers(app)

    # 4. 注册全局异常处理器
    handle_exception(app)

    return app