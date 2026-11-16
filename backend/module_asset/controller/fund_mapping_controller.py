"""基金映射模块 Controller(API 路由层)。"""

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
from module_asset.entity.vo.asset_vo import FundMappingModel
from module_asset.service.asset_allocation_service import AssetAllocationService
from utils.response_util import ResponseUtil


fund_mapping_controller = APIRouterPro(
    prefix='/asset/mapping',
    order_num=32,
    tags=['资产配置-基金映射'],
)


def _current_user_id() -> int:
    """从上下文取当前用户 ID(鉴权依赖已保证登录)。"""
    current = get_current_user_or_none()
    if current is None:
        return 0
    return current.user_id


@fund_mapping_controller.get(
    '/list',
    summary='获取基金映射列表接口',
    description='返回当前用户全部基金映射(装配基金与类别信息)',
    response_model=DataResponseModel,
)
@Log(title='基金映射', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_fund_mappings(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mapping:list')] = None,
) -> Response:
    """获取基金映射列表。"""
    mappings = await AssetAllocationService.get_fund_mappings_services(query_db, _current_user_id())
    return ResponseUtil.success(rows=mappings)


@fund_mapping_controller.get(
    '/unmapped',
    summary='获取未映射基金接口',
    description='返回当前用户持仓中尚未映射到资产类别的基金',
    response_model=DataResponseModel,
)
@Log(title='基金映射', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_unmapped_funds(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mapping:list')] = None,
) -> Response:
    """获取未映射基金。"""
    funds = await AssetAllocationService.get_unmapped_funds_services(query_db, _current_user_id())
    return ResponseUtil.success(rows=funds)


@fund_mapping_controller.post(
    '',
    summary='保存基金映射接口',
    description='创建或更新基金到资产类别的映射',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='fund_mapping_save',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='保存操作过于频繁，请稍后再试',
)
@Log(title='基金映射', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def map_fund_to_class(
    request: Request,
    mapping_info: FundMappingModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mapping:add')] = None,
) -> Response:
    """保存基金映射。"""
    result = await AssetAllocationService.map_fund_to_class_services(query_db, _current_user_id(), mapping_info)
    return ResponseUtil.success(msg=result.message)


@fund_mapping_controller.delete(
    '/{fund_id}',
    summary='删除基金映射接口',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='fund_mapping_delete',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除操作过于频繁，请稍后再试',
)
@Log(title='基金映射', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_fund_mapping(
    request: Request,
    fund_id: Annotated[int, Path(description='基金ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('asset:mapping:remove')] = None,
) -> Response:
    """删除基金映射。"""
    result = await AssetAllocationService.delete_fund_mapping_services(query_db, _current_user_id(), fund_id)
    return ResponseUtil.success(msg=result.message)
