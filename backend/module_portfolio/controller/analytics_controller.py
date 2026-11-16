"""持仓分析模块 Controller(API 路由层)。

收益率分析/历史持仓/占比历史接口,查询参数为标量 Query。
全域仅登录(行级隔离私域数据,不做按钮级权限,同 position_controller 头注)。
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.security import CurrentUser
from db.get_db import get_db
from module_fund.service.akshare_service import DEFAULT_BENCHMARK_INDEX
from module_portfolio.service.analytics_service import AnalyticsService
from module_portfolio.service.position_service import PositionService
from module_portfolio.service.risk_metrics_service import RiskMetricsService
from utils.response_util import ResponseUtil


analytics_controller = APIRouterPro(
    prefix='/portfolio/analytics',
    order_num=21,
    tags=['持仓分析'],
)


def _current_user_id() -> int:
    """从上下文取当前用户 ID(鉴权依赖已保证登录)。"""
    current = get_current_user_or_none()
    if current is None:
        return 0
    return current.user_id


@analytics_controller.get(
    '/overview',
    summary='获取持仓概览接口',
    description='总市值/总成本/总盈亏 + 持仓明细列表(饼图与排名数据源)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='analytics_overview',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
)
@Log(title='持仓分析', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_overview(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """获取持仓概览。"""
    overview = await PositionService.get_overview_services(
        query_db, request.app.state.redis, _current_user_id()
    )
    return ResponseUtil.success(data=overview)


@analytics_controller.get(
    '/history',
    summary='查询历史持仓接口',
    description='返回指定日期的持仓快照(历史份额/历史成本)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='analytics_history',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
)
@Log(title='持仓分析', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_history(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    query_date: Annotated[date, Query(description='查询日期')],
    current_user: CurrentUser,
) -> Response:
    """查询历史持仓。"""
    result = await AnalyticsService.get_portfolio_at_date_services(
        query_db, request.app.state.redis, _current_user_id(), query_date
    )
    return ResponseUtil.success(data=result)


@analytics_controller.get(
    '/history/returns',
    summary='获取收益率历史接口',
    description='折线图数据:简单收益率 + Modified Dietz 资金加权收益率 + 市值',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='analytics_history_returns',
    limit=20,
    period=60,
    scope='user',
    algorithm='sliding_window',
)
@Log(title='持仓分析', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_return_history(
    current_user: CurrentUser,
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    start_date: Annotated[date | None, Query(description='起始日期(默认结束日前90天)')] = None,
    end_date: Annotated[date | None, Query(description='结束日期(默认今天)')] = None,
    interval_days: Annotated[int, Query(ge=1, le=90, description='采样间隔天数')] = 7,
) -> Response:
    """获取收益率历史。"""
    target_end = end_date or date.today()
    target_start = start_date or target_end - timedelta(days=90)
    result = await AnalyticsService.get_portfolio_return_history_services(
        query_db, request.app.state.redis, _current_user_id(), target_start, target_end, interval_days
    )
    return ResponseUtil.success(data=result)


@analytics_controller.get(
    '/comparison',
    summary='获取收益率分析接口',
    description='TWR/MWR/基准对比/年化(Modified Dietz),优先走快照快速路径',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='analytics_comparison',
    limit=20,
    period=60,
    scope='user',
    algorithm='sliding_window',
)
@Log(title='持仓分析', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_analytics(
    current_user: CurrentUser,
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    start_date: Annotated[date | None, Query(description='起始日期(默认结束日前365天)')] = None,
    end_date: Annotated[date | None, Query(description='结束日期(默认今天)')] = None,
    interval_days: Annotated[int, Query(ge=1, le=90, description='采样间隔天数')] = 7,
    benchmark: Annotated[str, Query(description='基准指数名称')] = DEFAULT_BENCHMARK_INDEX,
) -> Response:
    """获取收益率分析。"""
    target_end = end_date or date.today()
    target_start = start_date or target_end - timedelta(days=365)
    result = await AnalyticsService.calculate_portfolio_analytics_services(
        query_db, request.app.state.redis, _current_user_id(), target_start, target_end, interval_days, benchmark
    )
    return ResponseUtil.success(data=result)


@analytics_controller.get(
    '/allocation-history',
    summary='获取持仓占比历史接口',
    description='每日各基金持仓占比及相比上日变化(依赖快照表)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='analytics_allocation_history',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
)
@Log(title='持仓分析', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_allocation_history(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    start_date: Annotated[date, Query(description='起始日期')],
    end_date: Annotated[date, Query(description='截止日期')],
    current_user: CurrentUser,
) -> Response:
    """获取持仓占比历史。"""
    result = await AnalyticsService.get_allocation_history_services(
        query_db, request.app.state.redis, _current_user_id(), start_date, end_date
    )
    return ResponseUtil.success(data=result)


@analytics_controller.get(
    '/position/{position_id}/return',
    summary='获取持仓收益率接口',
    description='单持仓简单收益率((市值-成本)/成本)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='analytics_position_return',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
)
@Log(title='持仓分析', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_position_return(
    current_user: CurrentUser,
    request: Request,
    position_id: Annotated[int, Path(description='持仓ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    as_of_date: Annotated[date | None, Query(description='统计日期(默认今天)')] = None,
) -> Response:
    """获取持仓收益率。"""
    result = await AnalyticsService.get_holding_return_services(
        query_db, request.app.state.redis, position_id, _current_user_id(), as_of_date or date.today()
    )
    return ResponseUtil.success(data=result)


@analytics_controller.get(
    '/position/{position_id}/annualized',
    summary='获取持仓年化收益率接口',
    description='单持仓 Modified Dietz 年化收益率',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='analytics_position_annualized',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
)
@Log(title='持仓分析', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_position_annualized(
    current_user: CurrentUser,
    request: Request,
    position_id: Annotated[int, Path(description='持仓ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    as_of_date: Annotated[date | None, Query(description='统计日期(默认今天)')] = None,
) -> Response:
    """获取持仓年化收益率。"""
    result = await AnalyticsService.calculate_position_dietz_return_services(
        query_db, request.app.state.redis, position_id, _current_user_id(), as_of_date or date.today()
    )
    return ResponseUtil.success(data=result)


@analytics_controller.get(
    '/daily-fund-profit',
    summary='获取逐基金日收益接口',
    description='最新净值日(今日档)与上一净值日(昨日档)两档并列的逐基金日收益',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='analytics_daily_fund_profit',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
)
@Log(title='持仓分析', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_daily_fund_profit(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """获取逐基金日收益(两档并列,净值 T+1 发布后昨日档不再被今日覆盖)。"""
    result = await AnalyticsService.get_daily_fund_profit_services(
        query_db, request.app.state.redis, _current_user_id()
    )
    return ResponseUtil.success(data=result)


@analytics_controller.get(
    '/risk-metrics',
    summary='获取持仓风险指标接口',
    description='年化波动率/最大回撤/夏普/索提诺/卡玛/信息比率/贝塔等专业指标(QuantStats),'
    '基于快照表日频市值组装日频 TWR 收益率;无快照或交易日不足返回空载荷',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='analytics_risk_metrics',
    limit=20,
    period=60,
    scope='user',
    algorithm='sliding_window',
)
@Log(title='持仓分析', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_risk_metrics(
    current_user: CurrentUser,
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    start_date: Annotated[date | None, Query(description='起始日期(默认结束日前365天)')] = None,
    end_date: Annotated[date | None, Query(description='结束日期(默认今天)')] = None,
    benchmark: Annotated[str, Query(description='基准指数名称')] = DEFAULT_BENCHMARK_INDEX,
) -> Response:
    """获取持仓风险指标(日频,逻辑在独立的 risk_metrics_service)。"""
    target_end = end_date or date.today()
    target_start = start_date or target_end - timedelta(days=365)
    result = await RiskMetricsService.calculate_risk_metrics_services(
        query_db, request.app.state.redis, _current_user_id(), target_start, target_end, benchmark
    )
    return ResponseUtil.success(data=result)


@analytics_controller.get(
    '/fund-risk-metrics',
    summary='获取基金风险指标接口',
    description='单基金年化波动率/最大回撤/夏普等专业指标(QuantStats),收益率序列直接取自'
    '复权净值相邻相除;时间档与基金详情收益率曲线同源,指标评估区间=曲线展示区间',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='analytics_fund_risk_metrics',
    limit=20,
    period=60,
    scope='user',
    algorithm='sliding_window',
)
@Log(title='持仓分析', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_fund_risk_metrics(
    current_user: CurrentUser,
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    fund_code: Annotated[str, Query(description='基金代码(6位)')],
    period: Annotated[str, Query(description='时间档,与收益率曲线档位一致')] = '1年',
    benchmark: Annotated[str, Query(description='基准指数名称')] = DEFAULT_BENCHMARK_INDEX,
) -> Response:
    """获取基金风险指标(复用持仓指标内核,收益率来自复权净值)。"""
    result = await RiskMetricsService.calculate_fund_risk_metrics_services(
        query_db, request.app.state.redis, fund_code, period, benchmark
    )
    return ResponseUtil.success(data=result)
