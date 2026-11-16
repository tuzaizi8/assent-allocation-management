"""认证模块 Controller（API 路由层）。

对接 react-scaffold 前端契约：/auth/login、/auth/me、/auth/logout、/auth/register。
路由经 APIRouterPro 自动注册（RouterRegister 扫描 */controller/[!_]*.py）。
"""

from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.rate_limit_annotation import ApiRateLimit
from common.constants import LogCategory
from common.response import DataResponseModel
from common.router import APIRouterPro
from core.security import CurrentUser, oauth2_scheme
from db.get_db import get_db
from module_system.entity.vo.auth_vo import (
    LoginModel,
    PasswordUpdateModel,
    ProfileUpdateModel,
    RegisterModel,
)
from module_system.service.auth_service import AuthService
from utils.response_util import ResponseUtil
from common.annotation.log_annotation import BusinessType, Log, LogMode


auth_controller = APIRouterPro(prefix='/auth', order_num=1, tags=['认证'])


@auth_controller.post('/login', summary='登录接口', description='邮箱 + 密码登录，签发 JWT')
@ApiRateLimit(
    namespace='auth_login',
    limit=10,
    period=60,
    scope='ip',
    algorithm='sliding_window',
    message='登录尝试过于频繁，请稍后再试',
)
@Log(title='认证管理', business_type=BusinessType.OTHER, mode=LogMode.AROUND, category=LogCategory.LOGIN)
async def login(
    request: Request,
    login_model: LoginModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """登录：认证 → 签发 JWT → 写 Redis 会话 → 返回 {jwt, user}。"""
    result = await AuthService.login_services(query_db, request.app.state.redis, login_model,request)
    return ResponseUtil.success(data=result)


@auth_controller.get('/me', summary='获取当前用户接口', description='解析 Bearer token 返回当前用户')
@Log(title='认证管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND, category=LogCategory.LOGIN)
async def get_current_user_info(
    request: Request,
    current_user: CurrentUser,
    token: Annotated[str, Depends(oauth2_scheme)],
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """获取当前登录用户（前端 userFn 启动时调用，刷新页面保持登录态）。"""
    user = await AuthService.get_current_user_services(
        query_db, request.app.state.redis, current_user, token
    )
    return ResponseUtil.success(data=user.model_dump(by_alias=True))


@auth_controller.post('/logout', summary='登出接口', description='清除 Redis 会话（幂等）')
@Log(title='认证管理', business_type=BusinessType.OTHER, mode=LogMode.AROUND, category=LogCategory.LOGIN)
async def logout(request: Request) -> Response:
    """登出：删除 Redis 会话。

    前端登出时序是「先清 localStorage 再发请求」，请求可能不带 Bearer，
    因此不用 oauth2_scheme 强制鉴权，手动提取 + 幂等处理。
    """
    token = request.headers.get('Authorization')
    if token and token.startswith('Bearer '):
        token = token.split(' ', 1)[1]
    await AuthService.logout_services(request.app.state.redis, token)
    return ResponseUtil.success(msg='退出成功')


@auth_controller.post('/register', summary='注册接口', description='邮箱注册，注册即登录')
@ApiRateLimit(
    namespace='auth_register',
    limit=5,
    period=60,
    scope='ip',
    algorithm='sliding_window',
    message='注册操作过于频繁，请稍后再试',
)
@Log(title='认证管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND, category=LogCategory.LOGIN)
async def register(
    request: Request,
    register_model: RegisterModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """注册：邮箱唯一校验 → bcrypt 加密落库 → 签发 JWT（注册即登录）。"""
    result = await AuthService.register_services(
        query_db, request.app.state.redis, register_model
    )
    return ResponseUtil.success(data=result)


@auth_controller.get(
    '/profile',
    summary='获取个人资料接口',
    description='当前登录者的资料:昵称与手机号可改,邮箱(登录账号)只读',
    response_model=DataResponseModel,
)
@Log(title='个人资料', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_profile(
    request: Request,
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """获取个人资料(仅需登录,无需额外权限——自己的数据自己看)。"""
    result = await AuthService.get_profile_services(query_db, current_user)
    return ResponseUtil.success(data=result.model_dump(by_alias=True))


@auth_controller.put(
    '/profile',
    summary='修改个人资料接口',
    description='自助修改昵称与手机号(请求体不接受邮箱/角色/状态等字段)',
    response_model=DataResponseModel,
)
@Log(title='个人资料', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def update_profile(
    request: Request,
    current_user: CurrentUser,
    profile_model: ProfileUpdateModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """修改个人资料:只落昵称与手机号两列。"""
    result = await AuthService.update_profile_services(query_db, current_user, profile_model)
    return ResponseUtil.success(data=result.model_dump(by_alias=True), msg='修改成功')


@auth_controller.put(
    '/password',
    summary='修改密码接口',
    description='校验原密码后更新为新密码,并作废当前会话(需用新密码重新登录)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='auth_password',
    limit=5,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='修改密码操作过于频繁，请稍后再试',
)
@Log(title='个人资料', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def update_password(
    request: Request,
    current_user: CurrentUser,
    password_model: PasswordUpdateModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """修改密码:限流防原密码爆破,改完作废会话。"""
    await AuthService.update_password_services(
        query_db, request.app.state.redis, current_user, password_model
    )
    return ResponseUtil.success(msg='密码修改成功，请重新登录')
