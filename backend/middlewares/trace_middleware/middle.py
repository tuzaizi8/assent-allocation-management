from functools import wraps

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .ctx import TraceCtx
from .span import Span, get_current_span

from utils.log import logger
import time

class TraceASGIMiddleware:
    """
    纯 ASGI Trace 中间件

    使用示例：
        app = FastAPI()
        app.add_middleware(TraceASGIMiddleware)
    """

    def __init__(self, app: ASGIApp) -> None:
        """
        :param app: 被包装的下一层 ASGI 应用
        """
        self.app = app

    @staticmethod
    async def my_receive(receive: Receive, span: Span) -> Receive:
        """
        包装 receive callable，在收到请求前调用 span.request_before()
        返回一个新的 receive 函数
        """
        await span.request_before()

        @wraps(receive)
        async def my_receive() -> Message:
            message = await receive()
            await span.request_after(message)
            return message

        return my_receive

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        ASGI 应用入口，所有请求都会经过这里
        """
        # 非 http 类型（如 lifespan、websocket）直接放行
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        # 进入 Span 上下文，开始请求生命周期
        async with get_current_span(scope) as span:
            # 1. 包装 receive：在首次 receive 时触发 request_before
            handle_outgoing_receive = await self.my_receive(receive, span)

            # 2. 包装 send：在发送响应时把 trace 头塞进 http.response.start
            async def handle_outgoing_request(message: 'Message') -> None:
                await span.response(message)
                await send(message)

            start_time = time.perf_counter()
            # 3. 调用下一层 app，传入包装后的 receive 和 send
            try:
                await self.app(scope, handle_outgoing_receive, handle_outgoing_request)
            finally:
                cost_ms = int((time.perf_counter() - start_time) * 1000)
                status = scope.get("response", {}).get("status", "?")
                # 访问日志:每个请求一行,带 trace_id(已由 patcher 注入)
                logger.info(f"{scope.get('method', '?')} {scope.get('path', '?')} → {status} {cost_ms}ms")
                # 4. 无论成功失败，都清理 trace 上下文
                TraceCtx.clear()