"""指数收益率管理 Controller(API 路由层)。

公共数据接口:不挂接口权限,但必须登录(CurrentUser 依赖)——与 /fund/chart/* 的口径一致。
"""

from typing import Annotated

from fastapi import Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel
from common.router import APIRouterPro
from core.security import CurrentUser
from db.get_db import get_db
from module_fund.service.index_service import IndexService
from utils.response_util import ResponseUtil


index_controller = APIRouterPro(
    prefix='/index',
    order_num=12,
    tags=['指数收益率管理'],
)


@index_controller.get(
    '/list',
    summary='获取指数列表接口',
    description='内置指数全集 + 库中缓存汇总(不分页,支持关键字与同步状态过滤)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='index_list',
    limit=60,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='指数查询过于频繁，请稍后再试',
)
@Log(title='指数收益率管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_index_list(
    request: Request,
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    keyword: Annotated[str | None, Query(description='指数名称/代码关键字')] = None,
    sync_status: Annotated[
        str | None, Query(alias='syncStatus', description='同步状态(all/1=已同步/0=未同步/2=已过期)')
    ] = None,
) -> Response:
    """获取指数列表。"""
    items = await IndexService.list_indices_services(query_db, keyword, sync_status)
    return ResponseUtil.success(data=items)


@index_controller.post(
    '/sync',
    summary='同步全部指数接口',
    description='对内置指数逐个强制回源(绕过缓存新鲜度),单指数失败不影响其余',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='index_sync_all',
    limit=4,
    period=3600,
    scope='user',
    algorithm='sliding_window',
    message='全量同步过于频繁，请稍后再试',
)
@Log(title='指数收益率管理', business_type=BusinessType.OTHER, mode=LogMode.AROUND)
async def sync_all_indices(
    request: Request,
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """同步全部内置指数。"""
    result = await IndexService.sync_all_services(query_db, request.app.state.redis)
    msg = f'成功同步 {result["success"]}/{result["total"]} 个指数'
    if result['failed']:
        msg += f'，失败：{"、".join(result["failed"])}'
    return ResponseUtil.success(data=result, msg=msg)


@index_controller.post(
    '/sync/{index_code}',
    summary='同步单个指数接口',
    description='强制回源单个指数并回写数据库与缓存',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='index_sync_one',
    limit=6,
    period=3600,
    scope='user',
    algorithm='sliding_window',
    message='指数同步过于频繁，请稍后再试',
)
@Log(title='指数收益率管理', business_type=BusinessType.OTHER, mode=LogMode.AROUND)
async def sync_one_index(
    request: Request,
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    index_code: Annotated[str, Path(description='指数代码(如 sh000300)')],
) -> Response:
    """同步单个指数。"""
    result = await IndexService.sync_one_services(query_db, request.app.state.redis, index_code)
    return ResponseUtil.success(
        msg=f'成功同步「{result["indexName"]}」{result["recordCount"]} 条行情数据', data=result
    )


@index_controller.get(
    '/{index_code}',
    summary='获取指数详情接口',
    description='元数据 + 区间收益率(1周/1月/3月/1年/成立以来) + 最近 10 个交易日明细',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='index_detail',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='指数查询过于频繁，请稍后再试',
)
@Log(title='指数收益率管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_index_detail(
    request: Request,
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    index_code: Annotated[str, Path(description='指数代码(如 sh000300)')],
) -> Response:
    """获取指数详情。"""
    detail = await IndexService.get_index_detail_services(
        query_db, request.app.state.redis, index_code
    )
    return ResponseUtil.success(data=detail)


@index_controller.delete(
    '/{index_codes}',
    summary='删除指数缓存接口',
    description='物理删除指数行情缓存行(逗号分隔),并连带清对应 Redis 缓存',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='index_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除操作过于频繁，请稍后再试',
)
@Log(title='指数收益率管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_indices(
    request: Request,
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    index_codes: Annotated[str, Path(description='需要删除的指数代码，多个用逗号分隔')],
) -> Response:
    """删除指数缓存。"""
    codes = [code.strip() for code in index_codes.split(',') if code.strip()]
    result = await IndexService.delete_indices_services(query_db, request.app.state.redis, codes)
    return ResponseUtil.success(msg=f'已清除 {result["deleted"]} 个指数的历史缓存', data=result)
