"""
上下文便捷函数

对业务层提供统一的上下文读写入口，屏蔽 RequestContext / TraceCtx 的内部细节。
业务代码只需 from core.context_utils import get_current_user, get_trace_id
"""
from core.context import CurrentUser, RequestContext, current_user
from middlewares.trace_middleware import TraceCtx


def get_current_user() -> CurrentUser:
    """
    获取当前登录用户

    :return: 当前登录用户
    :raises LoginException: 未登录时抛出
    """
    return RequestContext.get_current_user()


def get_current_user_or_none() -> CurrentUser | None:
    """
    获取当前登录用户，未登录时返回 None（不抛异常）

    适用于「登录可选」的接口：如公开接口里若用户已登录则个性化展示

    :return: 当前登录用户或 None
    """
    return current_user.get()


def get_trace_id() -> str:
    """
    获取当前请求的 trace_id

    :return: trace_id（未设置时返回空串）
    """
    return TraceCtx.get_trace_id()


def get_request_id() -> str:
    """
    获取当前请求的 request_id

    :return: request_id（未设置时返回空串）
    """
    return TraceCtx.get_request_id()


def get_span_id() -> str:
    """
    获取当前请求的 span_id

    :return: span_id（未设置时返回空串）
    """
    return TraceCtx.get_span_id()


def set_current_user(user: CurrentUser):
    """
    设置当前登录用户

    典型用法：在 JWT 鉴权依赖里解析出 user 后调用本函数写入上下文

    :param user: 当前登录用户
    :return: 上下文变量令牌，可用于后续 reset（依赖注入场景通常不需要 reset，
             因为请求结束会被 ContextCleanupMiddleware 统一清理）
    """
    return RequestContext.set_current_user(user)


def set_current_exclude_patterns(patterns) -> None:
    """
    设置当前请求的排除路由模式列表

    :param patterns: 编译后的排除路由模式列表
    """
    RequestContext.set_current_exclude_patterns(patterns)

def get_request_path() -> str:
    """
    获取当前请求路径

    :return: 请求路径(未设置时返回空串)
    """
    return TraceCtx.get_request_path()


def get_request_method() -> str:
    """
    获取当前请求方法

    :return: 请求方法(未设置时返回空串)
    """
    return TraceCtx.get_request_method()