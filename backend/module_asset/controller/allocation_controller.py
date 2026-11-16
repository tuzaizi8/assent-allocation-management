"""配置对比模块 Controller(API 路由层)。"""

from typing import Annotated

from fastapi import Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.response import DataResponseModel
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.interface_auth import CheckUserInterfaceAuth
from db.get_db import get_db
from module_asset.service.asset_allocation_service import AssetAllocationService
from utils.response_util import ResponseUtil


allocation_controller = APIRouterPro(
    prefix='/asset/allocation',
    order_num=33,
    tags=['资产配置-配置对比'],
)


@allocation_controller.get(
    '/compare',
    summary='获取配置对比接口',
    description='当前持仓占比 vs 目标占比对比(超配/低配/达标,含未映射部分)',
    response_model=DataResponseModel,
)
@Log(title='配置对比', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def compare_allocation(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    mode_id: Annotated[int, Query(description='配置模式ID')],
    _: Annotated[None, CheckUserInterfaceAuth('asset:allocation:compare')] = None,
) -> Response:
    """获取配置对比。"""
    current = get_current_user_or_none()
    user_id = current.user_id if current else 0
    result = await AssetAllocationService.compare_allocation_services(
        query_db, request.app.state.redis, user_id, mode_id
    )
    return ResponseUtil.success(data=result)
