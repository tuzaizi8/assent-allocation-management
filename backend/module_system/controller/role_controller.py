"""角色管理模块 Controller(API 路由层)。

角色管理页(2026-08-23)配套接口;契约见知识库《02-角色管理页》。
路由经 APIRouterPro 自动注册(RouterRegister 扫描 */controller/[!_]*.py)。
"""

from datetime import datetime
from typing import Annotated

from fastapi import Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel, PageResponseModel, ResponseBaseModel
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.interface_auth import CheckUserInterfaceAuth
from db.get_db import get_db
from module_system.entity.vo.role_vo import (
    DeleteRoleModel,
    RoleAddModel,
    RoleEditModel,
    RolePageQueryModel,
)
from module_system.service.role_service import RoleService
from utils.response_util import ResponseUtil


role_controller = APIRouterPro(
    prefix='/system/role',
    order_num=4,
    tags=['系统管理-角色管理'],
)


@role_controller.get(
    '/list',
    summary='获取角色分页列表接口',
    description='用于获取角色分页列表',
    response_model=PageResponseModel,
)
@ApiRateLimit(
    namespace='role_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='角色列表查询过于频繁，请稍后再试',
)
@Log(title='角色管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_role_list(
    request: Request,
    role_page_query: Annotated[RolePageQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:role:list')] = None,
) -> Response:
    """获取角色分页列表。"""
    role_page_query_result = await RoleService.get_role_list_services(query_db, role_page_query, is_page=True)
    return ResponseUtil.success(model_content=role_page_query_result)


@role_controller.get(
    '/{role_id}',
    summary='获取角色详情接口',
    description='返回角色信息 + menuIds(编辑回显勾选)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='role_detail',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='角色查询过于频繁，请稍后再试',
)
@Log(title='角色管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_role_detail(
    request: Request,
    role_id: Annotated[int, Path(description='角色ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:role:query')] = None,
) -> Response:
    """获取角色详情(含绑定菜单ID列表)。"""
    role = await RoleService.get_role_detail_services(query_db, role_id)
    return ResponseUtil.success(data=role)


@role_controller.post(
    '',
    summary='新增角色接口',
    description='新增角色并绑定菜单(含菜单勾选全集)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='role_add',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='新增角色操作过于频繁，请稍后再试',
)
@Log(title='角色管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def add_role(
    request: Request,
    add_role: RoleAddModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:role:add')] = None,
) -> Response:
    """新增角色。"""
    current = get_current_user_or_none()
    add_role.create_by = current.user_name if current else 'admin'
    add_role.create_time = datetime.now()
    add_role_result = await RoleService.add_role_services(query_db, add_role)
    return ResponseUtil.success(msg=add_role_result.message)


@role_controller.put(
    '',
    summary='编辑角色接口',
    description='编辑角色 + 菜单绑定全量替换(内置 admin 角色保护)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='role_update',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='修改角色操作过于频繁，请稍后再试',
)
@Log(title='角色管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def edit_role(
    request: Request,
    edit_role: RoleEditModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:role:edit')] = None,
) -> Response:
    """编辑角色。"""
    current = get_current_user_or_none()
    edit_role.update_by = current.user_name if current else 'admin'
    edit_role.update_time = datetime.now()
    edit_role_result = await RoleService.edit_role_services(query_db, edit_role)
    return ResponseUtil.success(msg=edit_role_result.message)


@role_controller.delete(
    '/{role_ids}',
    summary='删除角色接口',
    description='逻辑删除并解绑关联(内置 admin 角色不可删)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='role_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除角色操作过于频繁，请稍后再试',
)
@Log(title='角色管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_role(
    request: Request,
    role_ids: Annotated[str, Path(description='需要删除的角色ID，多个用逗号分隔')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:role:remove')] = None,
) -> Response:
    """删除角色(逻辑删除 + 解绑角色菜单/用户角色关联)。"""
    delete_role = DeleteRoleModel(
        roleIds=role_ids,
        updateBy=get_current_user_or_none().user_name if get_current_user_or_none() else 'admin',
        updateTime=datetime.now(),
    )
    delete_role_result = await RoleService.delete_role_services(query_db, delete_role)
    return ResponseUtil.success(msg=delete_role_result.message)
