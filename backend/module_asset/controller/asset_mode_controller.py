"""配置模式模块 Controller(API 路由层)。"""

from typing import Annotated

from fastapi import Depends, Path, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel, ResponseBaseModel
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.interface_auth import CheckUserInterfaceAuth
from db.get_db import get_db
from module_asset.entity.vo.asset_vo import (
    AssetClassModeAddModel,
    AssetClassModeEditModel,
    AssetClassTargetBatchModel,
)
from module_asset.service.asset_allocation_service import AssetAllocationService
from utils.response_util import ResponseUtil


asset_mode_controller = APIRouterPro(
    prefix='/asset/mode',
    order_num=31,
    tags=['资产配置-配置模式'],
)


def _current_user_id() -> int:
    """从上下文取当前用户 ID(鉴权依赖已保证登录)。"""
    current = get_current_user_or_none()
    if current is None:
        return 0
    return current.user_id


@asset_mode_controller.get(
    '/list',
    summary='获取配置模式列表接口',
    response_model=DataResponseModel,
)
@Log(title='配置模式', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_modes(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mode:list')] = None,
) -> Response:
    """获取配置模式列表。"""
    modes = await AssetAllocationService.get_modes_services(query_db, _current_user_id())
    return ResponseUtil.success(rows=modes)


@asset_mode_controller.post(
    '',
    summary='新增配置模式接口',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='asset_mode_add',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='新增操作过于频繁，请稍后再试',
)
@Log(title='配置模式', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def add_mode(
    request: Request,
    mode_info: AssetClassModeAddModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mode:add')] = None,
) -> Response:
    """新增配置模式。"""
    result = await AssetAllocationService.add_mode_services(query_db, _current_user_id(), mode_info)
    return ResponseUtil.success(msg=result.message)


@asset_mode_controller.put(
    '',
    summary='编辑配置模式接口',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='asset_mode_update',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='修改操作过于频繁，请稍后再试',
)
@Log(title='配置模式', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def edit_mode(
    request: Request,
    mode_info: AssetClassModeEditModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mode:edit')] = None,
) -> Response:
    """编辑配置模式。"""
    result = await AssetAllocationService.edit_mode_services(query_db, _current_user_id(), mode_info)
    return ResponseUtil.success(msg=result.message)


@asset_mode_controller.delete(
    '/{mode_id}',
    summary='删除配置模式接口',
    description='物理删除(级联清理该模式的目标占比)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='asset_mode_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除操作过于频繁，请稍后再试',
)
@Log(title='配置模式', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_mode(
    request: Request,
    mode_id: Annotated[int, Path(description='配置模式ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mode:remove')] = None,
) -> Response:
    """删除配置模式。"""
    result = await AssetAllocationService.delete_mode_services(query_db, _current_user_id(), mode_id)
    return ResponseUtil.success(msg=result.message)


@asset_mode_controller.post(
    '/{mode_id}/set-default',
    summary='设置默认模式接口',
    description='设为默认(同用户互斥,原默认自动取消)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='asset_mode_default',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='设置操作过于频繁，请稍后再试',
)
@Log(title='配置模式', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def set_default_mode(
    request: Request,
    mode_id: Annotated[int, Path(description='配置模式ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mode:edit')] = None,
) -> Response:
    """设置默认模式。"""
    result = await AssetAllocationService.set_default_mode_services(query_db, _current_user_id(), mode_id)
    return ResponseUtil.success(msg=result.message)


@asset_mode_controller.get(
    '/{mode_id}/targets',
    summary='获取模式目标占比接口',
    description='返回模式下全部目标占比(含类别名称/颜色与合计)',
    response_model=DataResponseModel,
)
@Log(title='配置模式', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_mode_targets(
    request: Request,
    mode_id: Annotated[int, Path(description='配置模式ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mode:query')] = None,
) -> Response:
    """获取模式目标占比。"""
    result = await AssetAllocationService.get_mode_targets_services(query_db, _current_user_id(), mode_id)
    return ResponseUtil.success(data=result)


@asset_mode_controller.put(
    '/{mode_id}/targets',
    summary='批量更新目标占比接口',
    description='全量替换语义(先删后插),占比合计须为 100%',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='asset_target_update',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='修改操作过于频繁，请稍后再试',
)
@Log(title='配置模式', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def update_mode_targets(
    request: Request,
    mode_id: Annotated[int, Path(description='配置模式ID')],
    targets_info: AssetClassTargetBatchModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mode:edit')] = None,
) -> Response:
    """批量更新目标占比。"""
    result = await AssetAllocationService.update_mode_targets_services(
        query_db, _current_user_id(), mode_id, targets_info
    )
    return ResponseUtil.success(msg='更新成功', data=result)
