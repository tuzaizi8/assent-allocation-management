from fastapi import FastAPI

from middlewares.context_middleware import add_context_cleanup_middleware
from middlewares.cors_middleware import add_cors_middleware
from middlewares.gzip_middleware import add_gzip_middleware
from middlewares.trace_middleware import add_trace_middleware


def handle_middleware(app: FastAPI) -> None:
    """
    全局中间件处理：按栈式包装的逆序注册

    注册顺序（代码顺序）  →  栈中位置  →  请求处理顺序
    1. context_cleanup   →  最内层     →  第 4 个处理请求
    2. cors              →  次内层     →  第 3 个处理请求
    3. gzip              →  次外层     →  第 2 个处理请求
    4. trace             →  最外层     →  第 1 个处理请求

    口诀：先注册的贴近路由，后注册的贴近客户端
    """
    # 1. 上下文清理（最内层，紧贴路由，保证业务一结束就清理）
    add_context_cleanup_middleware(app)
    # 2. 跨域（次内层）
    add_cors_middleware(app)
    # 3. gzip 压缩（次外层）
    add_gzip_middleware(app)
    # 4. trace（最外层，最早生成 trace_id，最晚追加响应头）
    add_trace_middleware(app)