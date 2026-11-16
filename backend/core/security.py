"""安全依赖：OAuth2 令牌提取 + 当前用户解析"""

from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer

from common.constants import ADMIN_ROLE_KEY, LOGIN_TOKEN_KEY
from exceptions.exceptions import AuthException, PermissionException
from utils.jwt_util import JwtUtil
from utils.log import logger

from core.context_utils import set_current_user
# ⚠️ 起别名:模块底部已有同名 Annotated 类型别名 CurrentUser(路由用的依赖别名),
#    若同名导入,调用时 CurrentUser(...) 会静默退化为构造普通 dict(F811)
from core.context import CurrentUser as CurrentUserModel

from db.get_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from module_system.dao.user_dao import UserDao
from module_system.dao.menu_dao import MenuDao

# OAuth2 令牌提取器
# tokenUrl 指向登录接口路径，用于 OpenAPI 文档的「Authorize」按钮跳转
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='login')


async def get_current_user(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """从令牌解析当前用户信息

    :param token: 由 oauth2_scheme 自动从 Authorization 头提取的令牌
    :return: payload 字典（含 user_id、username 等）
    :raises AuthException: 令牌无效或已过期（处理器映射 401）
    """
    # 1. 解码令牌，捕获所有 JWT 异常统一转 AuthException（→ 401）
    try:
        payload = JwtUtil.decode_token(token)
    except Exception as e:
        raise AuthException(message='令牌已失效，请重新登录') from e
    # 2. 校验 payload 必备字段（防伪造）
    user_id = payload.get('user_id')
    if user_id is None:
        raise AuthException(message='令牌不合法')
    # 3. 查库装配当前用户(实时——与 interface_auth 同一设计哲学,改名/停用/删号即时生效)
    #    get_user_by_id 只过滤 del_flag(停用用户可查,对齐 get_user_by_email 模式),
    #    停用判断在此显式拦截——保持"停用即 401"语义
    user = await UserDao.get_user_by_id(query_db, user_id)
    if user is None:
        logger.warning(f'[鉴权] 用户不存在/已删除 user_id={user_id}')
        raise AuthException(message='用户不存在或已被删除')
    if user.status != '0':
        logger.warning(f'[鉴权] 用户已停用 user_id={user_id}')
        raise AuthException(message='用户已停用')
    # 4. 会话校验(单设备登录语义的唯一落点):Redis 里的 token 必须与本请求一致。
    #    登出、被挤下线、改密都会删掉或覆盖这个 key → 旧 token 立刻失效,不必等 JWT 自身过期。
    #    只依赖 JWT 不校验会话曾让"挤下线"落空:旧 token 在 exp 之前对所有接口都还能用
    try:
        session_token = await request.app.state.redis.get(LOGIN_TOKEN_KEY.format(user_id=user_id))
    except Exception as exc:
        # Redis 抖动时 fail-open:JWT 本身仍是有效凭据(签名 + 24h 过期),把可用性问题
        # 放大成全站 401 不划算;与 @ApiRateLimit 的降级策略保持一致
        logger.warning(f'[鉴权] 会话校验跳过(Redis 不可用) user_id={user_id} | {exc}')
        session_token = token
    if session_token != token:
        logger.warning(f'[鉴权] 会话不匹配 user_id={user_id}(已登出/被挤下线/改过密码/Redis 被清)')
        raise AuthException(message='登录状态已失效，请重新登录')
    # 5. 角色查询:is_admin 与 build_auth_user/interface_auth 同源判定(角色 role_key 含 admin)
    role_keys = await MenuDao.get_user_role_keys(query_db, user_id)
    # 6. 写入请求上下文,五字段全部实装配
    #    (@Log / @ApiCache(vary_by_user) / @ApiRateLimit(scope='user') 从此读到真实用户)
    #    ContextCleanupMiddleware 每请求结束统一清理,无需手动 reset
    set_current_user(
        CurrentUserModel(
            user_id=user_id,
            user_name=user.user_name,  # 以库为准(payload 里的 user_name 可能已过期)
            nick_name=user.nick_name or "",
            dept_id=user.dept_id,
            is_admin=(ADMIN_ROLE_KEY in role_keys),
        )
    )
    logger.debug(f'[鉴权] token 解码成功 user_id={user_id} is_admin={ADMIN_ROLE_KEY in role_keys}')
    return payload


def get_current_active_user(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """校验当前用户是否已激活

    :param current_user: 由 get_current_user 注入的用户信息
    :return: 激活的用户信息
    :raises PermissionException: 用户已被禁用（处理器映射 403）
    """
    # TODO: status 取自 token payload,与 get_current_user 的库级停用拦截并存,评估是否移除本分支
    if current_user.get('status') == '0':
        raise PermissionException(message='用户已被禁用')
    return current_user


# 常用依赖类型别名（在路由中直接 Annotated 使用）
CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
ActiveUser = Annotated[dict[str, Any], Depends(get_current_active_user)]