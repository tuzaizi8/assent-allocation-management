"""菜单模块 Controller(API 路由层)。

getRouters 挂根路径(无前缀)——契约见 04 文档 5.1。
路由经 APIRouterPro 自动注册(prefix='' 合法,order_num 决定扫描排序)。
"""

from datetime import datetime
from typing import Annotated

from fastapi import Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.interface_auth import CheckUserInterfaceAuth
from core.security import CurrentUser
from db.get_db import get_db
from module_system.entity.vo.menu_vo import MenuAddModel, MenuEditModel, MenuQueryModel
from module_system.service.menu_service import MenuService
from utils.response_util import ResponseUtil

menu_controller = APIRouterPro(prefix='', order_num=2, tags=['菜单'])


@menu_controller.get('/getRouters', summary='获取当前用户动态菜单', description='按角色过滤的菜单树')
@Log(title='菜单管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_routers(
    request: Request,
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """获取当前登录用户的菜单树(前端 useMenu 消费,契约见 04 文档 5.1)。"""
    menus = await MenuService.get_routers_services(query_db, current_user.get('user_id'))
    return ResponseUtil.success(data=menus)

# ==================== 菜单管理页 CRUD(2026-08-23,契约见知识库《01-菜单管理页》) ====================


@menu_controller.get(
    '/system/menu/list',
    summary='获取菜单列表接口',
    description='全量菜单(含 F 按钮与隐藏项),前端组树展示;不分页',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='menu_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='菜单列表查询过于频繁，请稍后再试',
)
@Log(title='菜单管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_menu_list(
    request: Request,
    menu_query: Annotated[MenuQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:menu:list')] = None,
) -> Response:
    """获取菜单全量列表(menuName 模糊过滤可选)。"""
    menus = await MenuService.get_menu_list_services(query_db, menu_query.menu_name)
    return ResponseUtil.success(data=menus)


@menu_controller.post(
    '/system/menu',
    summary='新增菜单接口',
    description='新增目录/菜单/按钮',
)
@ApiRateLimit(
    namespace='menu_add',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='新增菜单操作过于频繁，请稍后再试',
)
@Log(title='菜单管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def add_menu(
    request: Request,
    add_menu: MenuAddModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:menu:add')] = None,
) -> Response:
    """新增菜单。"""
    # 审计字段:操作人来自请求上下文(B1 接线后 @Log 与鉴权依赖共享同一上下文)
    current = get_current_user_or_none()
    add_menu.create_by = current.user_name if current else 'admin'
    add_menu.create_time = datetime.now()
    add_menu_result = await MenuService.add_menu_services(query_db, add_menu)
    return ResponseUtil.success(msg=add_menu_result.message)


@menu_controller.put(
    '/system/menu',
    summary='编辑菜单接口',
    description='编辑菜单(防环:上级不能是自己或自己的子孙)',
)
@ApiRateLimit(
    namespace='menu_update',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='修改菜单操作过于频繁，请稍后再试',
)
@Log(title='菜单管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def edit_menu(
    request: Request,
    edit_menu: MenuEditModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:menu:edit')] = None,
) -> Response:
    """编辑菜单。"""
    current = get_current_user_or_none()
    edit_menu.update_by = current.user_name if current else 'admin'
    edit_menu.update_time = datetime.now()
    edit_menu_result = await MenuService.edit_menu_services(query_db, edit_menu)
    return ResponseUtil.success(msg=edit_menu_result.message)


@menu_controller.delete(
    '/system/menu/{menu_id}',
    summary='删除菜单接口',
    description='物理删除(存在子菜单/被角色引用时拒绝)',
)
@ApiRateLimit(
    namespace='menu_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除菜单操作过于频繁，请稍后再试',
)
@Log(title='菜单管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_menu(
    request: Request,
    menu_id: Annotated[int, Path(description='需要删除的菜单ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:menu:remove')] = None,
) -> Response:
    """删除菜单。"""
    delete_menu_result = await MenuService.delete_menu_services(query_db, menu_id)
    return ResponseUtil.success(msg=delete_menu_result.message)
