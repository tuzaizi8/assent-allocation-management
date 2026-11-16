"""资产类别模块 Controller(API 路由层)。"""

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
from module_asset.entity.vo.asset_vo import AssetClassAddModel, AssetClassEditModel
from module_asset.service.asset_allocation_service import AssetAllocationService
from utils.response_util import ResponseUtil


asset_class_controller = APIRouterPro(
    prefix='/asset/class',
    order_num=30,
    tags=['资产配置-资产类别'],
)


def _current_user_id() -> int:
    """从上下文取当前用户 ID(鉴权依赖已保证登录)。"""
    current = get_current_user_or_none()
    if current is None:
        return 0
    return current.user_id


@asset_class_controller.get(
    '/list',
    summary='获取资产类别列表接口',
    description='返回当前用户全部资产类别(按排序顺序)',
    response_model=DataResponseModel,
)
@Log(title='资产类别', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_asset_classes(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:class:list')] = None,
) -> Response:
    """获取资产类别列表。"""
    classes = await AssetAllocationService.get_asset_classes_services(query_db, _current_user_id())
    return ResponseUtil.success(rows=classes)


@asset_class_controller.post(
    '',
    summary='新增资产类别接口',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='asset_class_add',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='新增操作过于频繁，请稍后再试',
)
@Log(title='资产类别', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def add_asset_class(
    request: Request,
    asset_class_info: AssetClassAddModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:class:add')] = None,
) -> Response:
    """新增资产类别。"""
    result = await AssetAllocationService.add_asset_class_services(query_db, _current_user_id(), asset_class_info)
    return ResponseUtil.success(msg=result.message)


@asset_class_controller.put(
    '',
    summary='编辑资产类别接口',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='asset_class_update',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='修改操作过于频繁，请稍后再试',
)
@Log(title='资产类别', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def edit_asset_class(
    request: Request,
    asset_class_info: AssetClassEditModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:class:edit')] = None,
) -> Response:
    """编辑资产类别。"""
    result = await AssetAllocationService.edit_asset_class_services(query_db, _current_user_id(), asset_class_info)
    return ResponseUtil.success(msg=result.message)


@asset_class_controller.delete(
    '/{asset_class_id}',
    summary='删除资产类别接口',
    description='物理删除(被基金映射引用时拒删,目标占比级联清理)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='asset_class_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除操作过于频繁，请稍后再试',
)
@Log(title='资产类别', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_asset_class(
    request: Request,
    asset_class_id: Annotated[int, Path(description='资产类别ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:class:remove')] = None,
) -> Response:
    """删除资产类别。"""
    result = await AssetAllocationService.delete_asset_class_services(query_db, _current_user_id(), asset_class_id)
    return ResponseUtil.success(msg=result.message)
