"""基金管理模块 Controller(API 路由层):基金详细信息。

路由经 APIRouterPro 自动注册(RouterRegister 扫描 */controller/[!_]*.py)。

**注册顺序是硬约束**:`/info/list`、`/info/sync`、`POST /info` 必须定义在
`/info/{fund_code}` 之前,否则被路径参数抢先匹配(fund_code='list')。
"""

from typing import Annotated

from fastapi import Body, Depends, Path, Query, Request, Response
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.router import APIRouterPro
from core.interface_auth import CheckUserInterfaceAuth
from core.security import CurrentUser
from db.get_db import get_db
from module_fund.entity.vo.fund_info_vo import (
    FundInfoCreateModel,
    FundInfoPageQueryModel,
)
from module_fund.service.fund_info_service import FundInfoService
from utils.response_util import ResponseUtil


fund_info_controller = APIRouterPro(
    prefix='/fund',
    order_num=11,
    tags=['基金管理'],
)


# ===== 管理端点(必须先于 /info/{fund_code} 注册) =====


@fund_info_controller.get(
    '/info/list',
    summary='基金详细信息分页列表接口',
    description='窄投影分页(不含 info 大 JSON),join fund 带出名称与类型,支持代码模糊搜索',
    response_model=None,
)
@ApiRateLimit(
    namespace='fund_info_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='基金信息列表查询过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_fund_info_list(
    request: Request,
    page_query: Annotated[FundInfoPageQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:info:list')] = None,
) -> Response:
    """基金详细信息分页列表(管理页)。"""
    result = await FundInfoService.get_info_page_services(
        query_db,
        page_query.page_num,
        page_query.page_size,
        page_query.keyword,
    )
    return ResponseUtil.success(model_content=result)


@fund_info_controller.post(
    '/info/sync',
    summary='基金详细信息全量同步接口',
    description='遍历表内全部基金逐个强制回源同花顺刷新(单只失败只记清单不拖垮整批)',
)
@ApiRateLimit(
    namespace='fund_info_sync',
    limit=5,
    period=3600,
    scope='user',
    algorithm='sliding_window',
    message='基金信息同步过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def sync_fund_infos(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:info:sync')] = None,
) -> Response:
    """全量同步基金详细信息(逐只强制回源)。"""
    redis: aioredis.Redis = request.app.state.redis
    result = await FundInfoService.sync_all_services(query_db, redis)
    ok, failed = result['success'], result['failedCodes']
    msg = f'同步完成:成功 {ok} 只,失败 {len(failed)} 只'
    if failed:
        msg += f'({", ".join(failed[:5])}{"…" if len(failed) > 5 else ""})'
    return ResponseUtil.success(msg=msg, data=result)


@fund_info_controller.post(
    '/info/sync/{fund_code}',
    summary='单只基金详细信息同步接口',
    description='强制回源同花顺刷新单只基金档案(绕过 Redis 与 DB),回写库并刷缓存',
)
@ApiRateLimit(
    namespace='fund_info_sync_one',
    limit=10,
    period=3600,
    scope='user',
    algorithm='sliding_window',
    message='基金信息同步过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def sync_one_fund_info(
    request: Request,
    fund_code: Annotated[str, Path(max_length=20)],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:info:sync')] = None,
) -> Response:
    """单只强制回源刷新(行内同步按钮)。"""
    redis: aioredis.Redis = request.app.state.redis
    await FundInfoService.refresh_info_services(query_db, redis, fund_code)
    return ResponseUtil.success(msg=f'基金 {fund_code} 详细信息已同步')


@fund_info_controller.post(
    '/info',
    summary='新增基金详细信息接口',
    description='按基金代码回源同花顺抓取档案入库(已存在则拒绝,走同步更新)',
)
@ApiRateLimit(
    namespace='fund_info_add',
    limit=5,
    period=3600,
    scope='user',
    algorithm='sliding_window',
    message='基金信息新增过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def add_fund_info(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: CurrentUser,
    page_object: Annotated[FundInfoCreateModel, Body()],
) -> Response:
    """新增基金详细信息(按代码回源)。"""
    redis: aioredis.Redis = request.app.state.redis
    await FundInfoService.create_info_services(
        query_db, redis, page_object.fund_code
    )
    return ResponseUtil.success(msg=f'基金 {page_object.fund_code} 详细信息新增成功', data={'fund_code': page_object.fund_code})


@fund_info_controller.delete(
    '/info/{fund_code}',
    summary='删除基金详细信息接口',
    description='物理删除缓存行并清 Redis(删除后详情接口会重新回源,可随时恢复)',
)
@ApiRateLimit(
    namespace='fund_info_remove',
    limit=3,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='基金信息删除过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_fund_info(
    request: Request,
    fund_code: Annotated[str, Path(max_length=20)],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:info:remove')] = None,
) -> Response:
    """删除基金详细信息缓存行。"""
    redis: aioredis.Redis = request.app.state.redis
    await FundInfoService.delete_info_services(query_db, redis, fund_code)
    return ResponseUtil.success(msg=f'基金 {fund_code} 详细信息已删除')


# ===== 查询端点(注册顺序在管理端点之后:/info/{fund_code} 是路径参数) =====


@fund_info_controller.get(
    '/info/{fund_code}',
    summary='获取基金详细信息接口',
    description='按基金代码获取同花顺基金档案全量键值(Redis 1 小时 → 数据库 → akshare 回源)',
)
@ApiRateLimit(
    namespace='fund_info',
    limit=10,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='基金详情查询过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_fund_info(
    request: Request,
    fund_code: Annotated[str, Path(max_length=20)],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: CurrentUser,
) -> Response:
    """获取基金详细信息(三级缓存:Redis → DB → akshare)。"""
    redis: aioredis.Redis = request.app.state.redis
    info = await FundInfoService.get_fund_info_services(query_db, redis, fund_code)
    return ResponseUtil.success(data=info)
