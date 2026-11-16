from fastapi import FastAPI

from .ctx import TraceCtx
from .middle import TraceASGIMiddleware

__all__ = ('TraceASGIMiddleware', 'TraceCtx','add_trace_middleware')

__version__ = '0.1.0'


def add_trace_middleware(app: FastAPI) -> None:
    """
    添加 trace 中间件

    :param app: FastAPI 对象
    :return: None
    """
    app.add_middleware(TraceASGIMiddleware)