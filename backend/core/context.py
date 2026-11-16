"""
业务请求上下文

基于 ContextVar 封装，提供请求级别的「当前用户」与「排除路由模式」存储。
- 写入由依赖注入层（JWT 鉴权依赖）手动调用 set_* 完成
- 读取由业务 service 层通过 RequestContext.get_* 或 context_utils 完成
- 清理由 ContextCleanupMiddleware 在请求结束时统一调用 clear_all
"""
import re
from contextvars import ContextVar, Token
from typing import Literal

from exceptions.exceptions import LoginException
from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# 当前用户模型
# --------------------------------------------------------------------------- #
class CurrentUser(BaseModel):
    """当前登录用户的精简模型,可按需扩展字段(roles / permissions / data_scope 等)。"""

    user_id: int                          # 用户主键
    user_name: str                        # 登录账号
    nick_name: str = ''                   # 显示昵称
    dept_id: int | None = None            # 所属部门
    is_admin: bool = False                # 是否超管


# --------------------------------------------------------------------------- #
# ContextVar 定义
# --------------------------------------------------------------------------- #
# HTTP 方法字面量类型
HttpMethod = Literal['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']

# 存储当前请求的编译后的排除路由模式列表（用于权限拦截器跳过白名单路由）
current_exclude_patterns: ContextVar[
    list[dict[str, str | list[HttpMethod] | re.Pattern]] | None
] = ContextVar('current_exclude_patterns', default=None)

# 存储当前登录用户信息
current_user: ContextVar[CurrentUser | None] = ContextVar('current_user', default=None)


# --------------------------------------------------------------------------- #
# RequestContext 工具类
# --------------------------------------------------------------------------- #
class RequestContext:
    """
    请求上下文管理类，封装 ContextVar 的读写操作

    所有方法均为 staticmethod，调用方式：
        token = RequestContext.set_current_user(user)
        user = RequestContext.get_current_user()
        RequestContext.reset_current_user(token)
    """

    # -------------------------- current_user -------------------------- #
    @staticmethod
    def set_current_user(user: CurrentUser) -> Token:
        """
        设置当前用户信息

        :param user: 当前登录用户
        :return: 上下文变量令牌，用于 reset 回滚
        """
        return current_user.set(user)

    @staticmethod
    def get_current_user() -> CurrentUser:
        """
        获取当前用户信息

        :return: 当前登录用户
        :raises LoginException: 当前用户为空（未登录）时抛出
        """
        _current_user = current_user.get()
        if _current_user is None:
            raise LoginException(message='当前用户信息为空，请检查是否已登录')
        return _current_user

    @staticmethod
    def reset_current_user(token: Token) -> None:
        """
        重置当前用户信息到 set 之前的状态

        :param token: set_current_user 返回的令牌
        """
        current_user.reset(token)

    # ---------------------- current_exclude_patterns ---------------------- #
    @staticmethod
    def set_current_exclude_patterns(
        exclude_patterns: list[dict[str, str | list[HttpMethod] | re.Pattern]],
    ) -> Token:
        """
        设置当前请求的排除路由模式列表

        :param exclude_patterns: 编译后的排除路由模式列表
        :return: 上下文变量令牌，用于 reset 回滚
        """
        return current_exclude_patterns.set(exclude_patterns)

    @staticmethod
    def get_current_exclude_patterns() -> list[
        dict[str, str | list[HttpMethod] | re.Pattern]
    ]:
        """
        获取当前请求的排除路由模式列表

        :return: 排除路由模式列表（未设置时返回空列表）
        """
        _exclude_patterns = current_exclude_patterns.get()
        if _exclude_patterns is None:
            _exclude_patterns = []
        return _exclude_patterns

    @staticmethod
    def reset_current_exclude_patterns(token: Token) -> None:
        """
        重置排除路由模式列表到 set 之前的状态

        :param token: set_current_exclude_patterns 返回的令牌
        """
        current_exclude_patterns.reset(token)

    # ------------------------------ clear ------------------------------ #
    @staticmethod
    def clear_all() -> None:
        """
        清除所有业务上下文变量

        由 ContextCleanupMiddleware 在请求结束时调用，
        保证 ContextVar 不会泄漏到下一个请求
        """
        current_user.set(None)
        current_exclude_patterns.set(None)