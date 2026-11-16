from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from starlette.types import Message, Scope

from .ctx import TraceCtx


class Span:
    """
    表示一次 HTTP 请求的生命周期 Span
    生命周期：request(before) → request(after) → response(before) → response(after)

    重要：trace 三件套在 request_before 阶段同时写入 ContextVar 和 span 实例属性，
    response 阶段从 span 实例属性读取（不依赖 ContextVar），避免 ContextVar 被
    中间件 finally 清理后响应头读不到值的问题（Gzip 中间件会缓冲响应，导致
    send 调用被延迟到 clear 之后）。
    """

    def __init__(self, scope: Scope) -> None:
        self.scope = scope
        # 在 span 实例上缓存 trace 三件套，response 阶段从这里读
        self.trace_id: str = ''
        self.request_id: str = ''
        self.span_id: str = ''

    async def request_before(self) -> None:
        """
        请求前置处理：在收到请求时立即生成 trace 三件套并写入 ContextVar + span 实例
        """
        self.trace_id = TraceCtx.set_trace_id()
        self.request_id = TraceCtx.set_request_id()
        self.span_id = TraceCtx.set_span_id()
        TraceCtx.set_request_path(self.scope.get('path', ''))
        TraceCtx.set_request_method(self.scope.get('method', ''))

    async def request_after(self, message: Message) -> Message:
        """
        请求后置处理：可用于记录请求体
        示例 message: {'type': 'http.request', 'body': b'...', 'more_body': False}
        """
        return message

    async def response(self, message: Message) -> Message:
        """
        响应处理：在 http.response.start 时把 trace 三件套写入响应头
        从 span 实例属性读取（不依赖 ContextVar），避免被 clear 后读不到
        """
        if message['type'] == 'http.response.start':
            # ASGI 响应头是 list[tuple[bytes, bytes]]，必须用 bytes
            message['headers'].append((b'request-id', self.request_id.encode()))
            message['headers'].append((b'trace-id', self.trace_id.encode()))
            message['headers'].append((b'span-id', self.span_id.encode()))
        return message


@asynccontextmanager
async def get_current_span(scope: Scope) -> AsyncGenerator[Span, None]:
    """
    Span 上下文管理器：yield 一个 Span 实例
    使用方式：async with get_current_span(scope) as span: ...
    """
    yield Span(scope)