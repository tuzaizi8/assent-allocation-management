"""上下文清理中间件（纯 ASGI 实现）

使用纯 ASGI 而非 BaseHTTPMiddleware，避免后者将响应体拆分为多 chunk
（more_body=True），导致 GZipMiddleware 误判为流式响应而强制压缩小响应。

在每个请求处理完成后，统一清理所有基于 ContextVar 的上下文：
- TraceCtx：trace_id / request_id / span_id / path / method（追踪类）
- RequestContext：current_user / current_exclude_patterns（业务类）

确保 ContextVar 不会泄漏到下一个请求，避免协程间变量污染。
"""
from fastapi import FastAPI

from starlette.types import ASGIApp, Receive, Scope, Send

from middlewares.trace_middleware import TraceCtx
from core.context import RequestContext


class ContextCleanupMiddleware:
    """
    上下文清理中间件（纯 ASGI）

    在每个请求处理完成后清理 ContextVar，防止协程间变量污染。
    使用纯 ASGI 实现，避免 BaseHTTPMiddleware 的 task 拆分行为。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            # 无论成功失败，都清理上下文
            # 1. 清理追踪类上下文（trace_id 等）
            TraceCtx.clear()
            # 2. 清理业务类上下文（current_user 等）
            RequestContext.clear_all()


def add_context_cleanup_middleware(app: FastAPI) -> None:
    """
    添加上下文清理中间件

    :param app: FastAPI 对象
    :return: None
    """
    app.add_middleware(ContextCleanupMiddleware)
