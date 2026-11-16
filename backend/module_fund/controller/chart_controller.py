"""基金图表 Controller(API 路由层)。

公共数据接口:不挂接口权限,但必须登录(CurrentUser 依赖)。
"""

from datetime import date
from typing import Annotated

from fastapi import Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel
from common.router import APIRouterPro
from core.security import CurrentUser
from db.get_db import get_db
from module_fund.service.chart_service import CHART_PERIODS, ChartService
from utils.response_util import ResponseUtil


chart_controller = APIRouterPro(
    prefix='/fund/chart',
    order_num=11,
    tags=['基金图表'],
)


@chart_controller.get(
    '/yield-curve',
    summary='获取基金收益率曲线接口',
    description=f'复权净值视图,时间段过滤({"、".join(CHART_PERIODS)})',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='chart_yield_curve',
    limit=60,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='图表查询过于频繁，请稍后再试',
)
@Log(title='基金图表', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_yield_curve(
    request: Request,
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    fund_code: Annotated[str, Query(description='基金代码')],
    period: Annotated[str, Query(description='时间范围(1月/3月/6月/1年/5年/成立以来)')] = '1年',
) -> Response:
    """获取基金收益率曲线数据。"""
    result = await ChartService.get_yield_curve(query_db, request.app.state.redis, fund_code, period)
    return ResponseUtil.success(data=result)


@chart_controller.get(
    '/raw-nav',
    summary='获取基金原始净值走势接口',
    description=f'原始累计净值视图(净值走势图用,含 has_raw_accum_nav 标记),时间段过滤({"、".join(CHART_PERIODS)})',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='chart_raw_nav',
    limit=60,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='图表查询过于频繁，请稍后再试',
)
@Log(title='基金图表', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_raw_nav(
    request: Request,
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    fund_code: Annotated[str, Query(description='基金代码')],
    period: Annotated[str, Query(description='时间范围(1月/3月/6月/1年/5年/成立以来)')] = '1年',
) -> Response:
    """获取基金原始净值走势数据。"""
    result = await ChartService.get_raw_nav(query_db, request.app.state.redis, fund_code, period)
    return ResponseUtil.success(data=result)


@chart_controller.get(
    '/index-yields',
    summary='获取指数收益率曲线接口',
    description=f'收盘点位归一化(与基金收益率曲线同构),时间段过滤({"、".join(CHART_PERIODS)});'
    '或传 start_date/end_date 按自定义区间过滤(此时忽略 period)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='chart_index_yields',
    limit=60,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='图表查询过于频繁，请稍后再试',
)
@Log(title='基金图表', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_index_yield(
    request: Request,
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    index_name: Annotated[str, Query(alias='indexName', description='指数名称(如 沪深300)')],
    period: Annotated[str, Query(description='时间范围(1月/3月/6月/1年/5年/成立以来;传了自定义区间时忽略)')] = '1年',
    start_date: Annotated[date | None, Query(description='起始日期(自定义区间,缺省为结束日前 365 天)')] = None,
    end_date: Annotated[date | None, Query(description='结束日期(自定义区间,缺省今天)')] = None,
) -> Response:
    """获取指数收益率曲线数据。"""
    result = await ChartService.get_index_yield(
        query_db, request.app.state.redis, index_name, period, start_date, end_date
    )
    return ResponseUtil.success(data=result)
