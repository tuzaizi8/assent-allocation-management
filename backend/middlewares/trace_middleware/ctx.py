import contextvars
from uuid import uuid4

# 定义请求级别的上下文变量（ContextVar 在协程间隔离）
CTX_TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar('trace-id', default='')
CTX_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar('request-id', default='')
CTX_SPAN_ID: contextvars.ContextVar[str] = contextvars.ContextVar('span-id', default='')
CTX_REQUEST_PATH: contextvars.ContextVar[str] = contextvars.ContextVar('request-path', default='')
CTX_REQUEST_METHOD: contextvars.ContextVar[str] = contextvars.ContextVar('request-method', default='')


class TraceCtx:
    """
    Trace 上下文工具类，封装 ContextVar 的读写操作
    所有方法均为 staticmethod，调用方式：TraceCtx.set_trace_id()
    """

    @staticmethod
    def set_trace_id() -> str:
        """生成并设置 trace_id，返回生成的值"""
        _id = uuid4().hex
        CTX_TRACE_ID.set(_id)
        return _id

    @staticmethod
    def get_trace_id() -> str:
        """获取当前协程的 trace_id"""
        return CTX_TRACE_ID.get()

    @staticmethod
    def set_request_id() -> str:
        """生成并设置 request_id（单次请求唯一）"""
        _id = uuid4().hex
        CTX_REQUEST_ID.set(_id)
        return _id

    @staticmethod
    def get_request_id() -> str:
        return CTX_REQUEST_ID.get()

    @staticmethod
    def set_span_id() -> str:
        """生成并设置 span_id（可在请求内细分多个 span）"""
        _id = uuid4().hex
        CTX_SPAN_ID.set(_id)
        return _id

    @staticmethod
    def get_span_id() -> str:
        return CTX_SPAN_ID.get()

    @staticmethod
    def set_request_path(path: str) -> None:
        CTX_REQUEST_PATH.set(path)

    @staticmethod
    def get_request_path() -> str:
        return CTX_REQUEST_PATH.get()

    @staticmethod
    def set_request_method(method: str) -> None:
        CTX_REQUEST_METHOD.set(method)

    @staticmethod
    def get_request_method() -> str:
        return CTX_REQUEST_METHOD.get()

    @staticmethod
    def clear() -> None:
        """清空所有 trace 上下文（请求结束时调用）"""
        CTX_TRACE_ID.set('')
        CTX_REQUEST_ID.set('')
        CTX_SPAN_ID.set('')
        CTX_REQUEST_PATH.set('')
        CTX_REQUEST_METHOD.set('')