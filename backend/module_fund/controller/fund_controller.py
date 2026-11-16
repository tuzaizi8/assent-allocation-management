"""基金管理模块 Controller(API 路由层)。

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
from core.security import CurrentUser
from db.get_db import get_db
from module_fund.entity.vo.fund_vo import (
    DeleteFundModel,
    FundAddModel,
    FundEditModel,
    FundNavQueryModel,
    FundPageQueryModel,
)
from module_fund.service.chart_service import CHART_PERIODS
from module_fund.service.fund_service import FundService
from utils.response_util import ResponseUtil


fund_controller = APIRouterPro(
    prefix='/fund',
    order_num=10,
    tags=['基金管理'],
)

# 候选搜索的每页上限:下拉最多展示 20 条,避免这个公共端点被当列表接口用
CANDIDATE_MAX_PAGE_SIZE = 20


@fund_controller.get(
    '/list',
    summary='获取基金分页列表接口',
    description='用于获取基金分页列表(代码/名称/类型/状态动态条件)',
    response_model=PageResponseModel,
)
@ApiRateLimit(
    namespace='fund_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='基金列表查询过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_fund_list(
    request: Request,
    fund_page_query: Annotated[FundPageQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:fund:list')] = None,
) -> Response:
    """获取基金分页列表。"""
    fund_page_query_result = await FundService.get_fund_list_services(query_db, fund_page_query, is_page=True)
    return ResponseUtil.success(model_content=fund_page_query_result)


# 注册顺序是硬约束:FastAPI 按注册顺序匹配路由,'/types' 必须排在 '/{fund_id}' 之前——
# 否则请求 /fund/types 会先命中详情路由(fund_id='types' → int 校验失败 → 422)
@fund_controller.get(
    '/types',
    summary='获取基金类型选项接口',
    description='返回库内现有的基金类型(distinct 升序),供列表页类型筛选下拉使用',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='fund_types',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='基金类型查询过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
# 2026-10-08 去掉 fund:fund:list:类型与 /candidates 同为公共参考数据,
# 基金管理页的新增/编辑表单要用它,而无该菜单权限的普通账号也应当能正常建仓
async def get_fund_types(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """获取基金类型选项。"""
    types = await FundService.get_fund_types_services(query_db)
    return ResponseUtil.success(data=types)


# 注册顺序同 /types:'/periods' 必须排在 '/{fund_id}' 之前,否则被详情路由抢先命中。
# 不挂接口权限只挂 CurrentUser:时间档是所有登录用户看图表都要用的公共选项,
# 与 /fund/chart/* 同口径——逐用户配权限无意义,无 fund:fund:list 的普通用户仪表盘也要消费
@fund_controller.get(
    '/periods',
    summary='获取图表时间档选项接口',
    description='返回后端支持的时间档(与 filter_records_by_period 同源)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='fund_periods',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='时间档查询过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_fund_periods(
    request: Request,
    current_user: CurrentUser,
) -> Response:
    """获取图表时间档选项。"""
    return ResponseUtil.success(data=CHART_PERIODS)


# 注册顺序同 /types、/periods:'/candidates' 必须排在 '/{fund_id}' 之前,否则被详情路由抢先命中。
# **不挂接口权限只挂 CurrentUser**:基金代码/名称是**公共参考数据**,而 `/list` 的
# `fund:fund:list` 是「基金管理」菜单的权限标识——用它去卡录入控件(建仓/买入选基金),
# 会让没有该菜单的普通账号连建仓都做不了;反过来为用控件而授予该权限,又会让普通账号多出
# 基金管理菜单。与 /fund/periods、/fund/chart/*、/index/* 同口径(公共数据仅登录)。
@fund_controller.get(
    '/candidates',
    summary='获取基金候选接口',
    description='按代码或名称模糊搜索基金候选(供建仓/买入与净值页的选择器使用,最多 20 条)',
    response_model=PageResponseModel,
)
@ApiRateLimit(
    namespace='fund_candidates',
    limit=60,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='基金搜索过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_fund_candidates(
    request: Request,
    fund_page_query: Annotated[FundPageQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """获取基金候选(仅登录,公共参考数据)。"""
    # 候选只用于下拉:不管前端要多少,上限 20 条( fund 表两万多行,防止被当列表接口用 )
    fund_page_query.page_size = min(fund_page_query.page_size, CANDIDATE_MAX_PAGE_SIZE)
    fund_page_query.page_num = 1
    candidates = await FundService.get_fund_list_services(query_db, fund_page_query, is_page=True)
    return ResponseUtil.success(model_content=candidates)


@fund_controller.get(
    '/{fund_id}',
    summary='获取基金详情接口',
    description='按主键返回基金信息',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='fund_detail',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='基金查询过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_fund_detail(
    request: Request,
    fund_id: Annotated[int, Path(description='基金ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:fund:query')] = None,
) -> Response:
    """获取基金详情。"""
    fund = await FundService.get_fund_detail_services(query_db, fund_id)
    return ResponseUtil.success(data=fund)


@fund_controller.post(
    '',
    summary='新增基金接口',
    description='新增基金(代码唯一性前置校验)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='fund_add',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='新增基金操作过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def add_fund(
    request: Request,
    add_fund: FundAddModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:fund:add')] = None,
) -> Response:
    """新增基金。"""
    current = get_current_user_or_none()
    add_fund.create_by = current.user_name if current else 'admin'
    add_fund.create_time = datetime.now()
    add_fund_result = await FundService.add_fund_services(query_db, add_fund)
    return ResponseUtil.success(msg=add_fund_result.message)


@fund_controller.put(
    '',
    summary='编辑基金接口',
    description='编辑基金(持仓引用中的基金可改信息不可删)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='fund_update',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='修改基金操作过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def edit_fund(
    request: Request,
    edit_fund: FundEditModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:fund:edit')] = None,
) -> Response:
    """编辑基金。"""
    current = get_current_user_or_none()
    edit_fund.update_by = current.user_name if current else 'admin'
    edit_fund.update_time = datetime.now()
    edit_fund_result = await FundService.edit_fund_services(query_db, edit_fund)
    return ResponseUtil.success(msg=edit_fund_result.message)


@fund_controller.delete(
    '/{fund_ids}',
    summary='删除基金接口',
    description='逻辑删除(被持仓引用的基金拒删)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='fund_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除基金操作过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_fund(
    request: Request,
    fund_ids: Annotated[str, Path(description='需要删除的基金ID，多个用逗号分隔')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:fund:remove')] = None,
) -> Response:
    """删除基金(逻辑删除)。"""
    delete_fund = DeleteFundModel(
        fundIds=fund_ids,
        updateBy=get_current_user_or_none().user_name if get_current_user_or_none() else 'admin',
        updateTime=datetime.now(),
    )
    delete_fund_result = await FundService.delete_fund_services(query_db, delete_fund)
    return ResponseUtil.success(msg=delete_fund_result.message)


@fund_controller.post(
    '/sync',
    summary='全量同步基金接口',
    description='从 AkShare(天天基金)拉取全部基金基本信息落库,已存在代码跳过',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='fund_sync',
    limit=4,
    period=3600,
    scope='user',
    algorithm='sliding_window',
    message='全量同步过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.OTHER, mode=LogMode.AROUND)
async def sync_funds(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:fund:sync')] = None,
) -> Response:
    """全量同步基金基础信息。"""
    count = await FundService.sync_funds_services(query_db)
    return ResponseUtil.success(msg=f'成功同步 {count} 条基金数据')


# 注册顺序是硬约束:'/nav/list' 必须排在 '/nav/{fund_code}' 之前,否则 list 被路径参数抢先匹配
@fund_controller.get(
    '/nav/list',
    summary='获取基金净值分页列表接口',
    description='净值行窄投影分页(不含 nav_data 大 JSON),JOIN fund 带出名称,支持代码/名称模糊与三态同步状态过滤',
    response_model=PageResponseModel,
)
@ApiRateLimit(
    namespace='fund_nav_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='净值列表查询过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_fund_nav_list(
    request: Request,
    fund_nav_query: Annotated[FundNavQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:nav:list')] = None,
) -> Response:
    """获取基金净值分页列表。"""
    fund_nav_page_result = await FundService.get_nav_page_services(query_db, fund_nav_query)
    return ResponseUtil.success(model_content=fund_nav_page_result)


@fund_controller.post(
    '/nav/{fund_code}',
    summary='同步基金净值接口',
    description='拉取单只基金历史净值(经 akshare 获取并回写 DB 与 Redis),净值管理页按需同步用',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='fund_nav_sync',
    limit=10,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='净值同步操作过于频繁，请稍后再试',
)
@Log(title='基金管理', business_type=BusinessType.OTHER, mode=LogMode.AROUND)
async def sync_fund_nav(
    request: Request,
    fund_code: Annotated[str, Path(description='基金代码')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('fund:nav:sync')] = None,
) -> Response:
    """同步单只基金净值。"""
    records = await FundService.sync_fund_nav_services(query_db, request.app.state.redis, fund_code)
    return ResponseUtil.success(msg=f'获取到 {len(records)} 条净值记录', data=records)
