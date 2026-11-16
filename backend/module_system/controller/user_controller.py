"""用户管理模块 Controller（API 路由层）。

使用 APIRouterPro 注册路由，Depends(get_db) 注入数据库会话，
ResponseUtil 封装统一响应。
"""

from datetime import datetime
from typing import Annotated

from fastapi import Path, Query, Request, Response, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.cache_annotation import ApiCache, ApiCacheEvict
from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit

from common.router import APIRouterPro
from common.response import DataResponseModel, PageResponseModel, ResponseBaseModel
from db.get_db import get_db
from module_system.entity.vo.user_vo import (
    DeleteUserModel,
    UserAddModel,
    UserEditModel,
    UserPageQueryModel,
)
from module_system.service.user_service import UserService
from utils.log import logger
from utils.pwd_util import PwdUtil
from utils.response_util import ResponseUtil

from core.context_utils import get_current_user_or_none
from core.interface_auth import CheckUserInterfaceAuth

# 创建路由器：prefix 统一前缀，order_num 控制注册顺序，tags 用于 Swagger 分组
user_controller = APIRouterPro(
    prefix='/system/user',
    order_num=3,
    tags=['系统管理-用户管理'],
)


@user_controller.get(
    '/list',
    summary='获取用户分页列表接口',
    description='用于获取用户分页列表',
    response_model=PageResponseModel,
)
@ApiRateLimit(
    namespace='user_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='用户列表查询过于频繁，请稍后再试',
)
@ApiCache(namespace='user_list', expire_seconds=300, vary_by_user=True)
@Log(title='用户管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_system_user_list(
    request: Request,
    user_page_query: Annotated[UserPageQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:user:list')] = None,  # ← 放最后
) -> Response:
    """获取用户分页列表。"""
    user_page_query_result = await UserService.get_user_list_services(
        query_db, user_page_query, is_page=True
    )
    logger.info(f'[用户] 列表查询成功 page={user_page_query.page_num} size={user_page_query.page_size}')
    return ResponseUtil.success(model_content=user_page_query_result)


@user_controller.get(
    '/{user_id}',
    summary='获取用户详情接口',
    description='用于获取用户详细信息',
    response_model=DataResponseModel,
)
@ApiCache(namespace='user_detail', expire_seconds=60, vary_by_user=True)
@Log(title='用户管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_system_user_detail(
    request: Request,
    user_id: Annotated[int, Path(description='用户ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """获取用户详细信息(含 roleIds，编辑弹窗勾选回显用)。"""
    user_detail_result = await UserService.user_detail_services(query_db, user_id)
    logger.info(f'[用户] 详情查询成功 user_id={user_id}')
    # service 已返回驼峰 dict(含 roleIds、不含 password)，直接下发
    return ResponseUtil.success(data=user_detail_result)


@user_controller.post(
    '',
    summary='新增用户接口',
    description='用于新增用户',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='user_add',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='新增用户操作过于频繁，请稍后再试',
)
@ApiCacheEvict(evict_keys=['user_list', 'user_detail'])
@Log(title='用户管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def add_system_user(
    request: Request,
    add_user: UserAddModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """新增用户。"""
    # 密码加密（接口入参预处理）
    if add_user.password:
        add_user.password = PwdUtil.get_password_hash(add_user.password)
    # 审计字段取请求上下文:与同文件 edit/delete 及各业务 controller 同口径,
    # 否则新增用户的创建人恒为 'admin',操作日志归因失真
    current = get_current_user_or_none()
    add_user.create_by = current.user_name if current else 'admin'
    add_user.create_time = datetime.now()
    add_user.update_by = current.user_name if current else 'admin'
    add_user.update_time = datetime.now()
    add_user_result = await UserService.add_user_services(query_db, add_user)
    logger.info(add_user_result.message)
    return ResponseUtil.success(msg=add_user_result.message)


@user_controller.put(
    '',
    summary='编辑用户接口',
    description='用于编辑用户',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='user_update',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='修改用户操作过于频繁，请稍后再试',
)
@ApiCacheEvict(evict_keys=['user_list', 'user_detail'])
@Log(title='用户管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def edit_system_user(
    request: Request,
    edit_user: UserEditModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:user:edit')] = None,  # ← 接口权限
) -> Response:
    """编辑用户。"""
    # 密码加密(可选重置:传了才更新,空串在 service 层剔除)
    if edit_user.password:
        edit_user.password = PwdUtil.get_password_hash(edit_user.password)
    # 审计字段取请求上下文(B1 接线后,对齐 role_controller 范式)
    current = get_current_user_or_none()
    edit_user.update_by = current.user_name if current else 'admin'
    edit_user.update_time = datetime.now()
    edit_user_result = await UserService.edit_user_services(query_db, edit_user)
    logger.info(edit_user_result.message)
    return ResponseUtil.success(msg=edit_user_result.message)


@user_controller.delete(
    '/{user_ids}',
    summary='删除用户接口',
    description='用于删除用户（逻辑删除）',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='user_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除用户操作过于频繁，请稍后再试',
)
@ApiCacheEvict(evict_keys=['user_list', 'user_detail'])
@Log(title='用户管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_system_user(
    request: Request,
    user_ids: Annotated[str, Path(description='需要删除的用户ID，多个用逗号分隔')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """删除用户（逻辑删除，支持逗号分隔批量）。"""
    # 审计字段取请求上下文(B1 接线后，对齐 role_controller 范式)
    current = get_current_user_or_none()
    delete_user = DeleteUserModel(
        userIds=user_ids,
        updateBy=current.user_name if current else 'admin',
        updateTime=datetime.now(),
    )
    delete_user_result = await UserService.delete_user_services(query_db, delete_user)
    logger.info(delete_user_result.message)
    return ResponseUtil.success(msg=delete_user_result.message)