"""持仓快照模块 Controller(API 路由层)。

快照生成/状态查询/重建接口。
全域仅登录(行级隔离私域数据,不做按钮级权限,同 position_controller 头注)。
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import Annotated

from fastapi import Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel, PageResponseModel
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.security import CurrentUser
from db.get_db import get_db
from module_portfolio.dao.daily_snapshot_dao import DailySnapshotDao
from module_portfolio.entity.vo.snapshot_vo import SnapshotPageQueryModel
from module_portfolio.service.snapshot_service import SnapshotService
from utils.response_util import ResponseUtil


snapshot_controller = APIRouterPro(
    prefix='/portfolio/snapshot',
    order_num=22,
    tags=['持仓快照'],
)


def _current_user_id() -> int:
    """从上下文取当前用户 ID(鉴权依赖已保证登录)。"""
    current = get_current_user_or_none()
    if current is None:
        return 0
    return current.user_id


@snapshot_controller.post(
    '/generate',
    summary='生成持仓快照接口',
    description='生成日期区间的每日快照与现金流(区间大时耗时较长)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='snapshot_generate',
    limit=10,
    period=3600,
    scope='user',
    algorithm='sliding_window',
    message='快照生成过于频繁，请稍后再试',
)
@Log(title='持仓快照', business_type=BusinessType.OTHER, mode=LogMode.AROUND)
async def generate_snapshots(
    current_user: CurrentUser,
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    start_date: Annotated[date | None, Query(description='起始日期(默认结束日前90天)')] = None,
    end_date: Annotated[date | None, Query(description='结束日期(默认今天)')] = None,
) -> Response:
    """生成每日持仓快照。"""
    target_end = end_date or date.today()
    target_start = start_date or target_end - timedelta(days=90)
    result = await SnapshotService.generate_and_save_range_services(
        query_db, request.app.state.redis, _current_user_id(), target_start, target_end
    )
    return ResponseUtil.success(data=result)


@snapshot_controller.get(
    '/status',
    summary='查看快照状态接口',
    description='返回区间内快照数量/有数据日期数/最新快照日与样例',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='snapshot_status',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='快照状态查询过于频繁，请稍后再试',
)
@Log(title='持仓快照', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_snapshots_status(
    current_user: CurrentUser,
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    start_date: Annotated[date | None, Query(description='起始日期(默认结束日前90天)')] = None,
    end_date: Annotated[date | None, Query(description='结束日期(默认今天)')] = None,
) -> Response:
    """查看快照生成状态。"""
    target_end = end_date or date.today()
    target_start = start_date or target_end - timedelta(days=90)
    user_id = _current_user_id()
    snapshots = await DailySnapshotDao.get_snapshots_in_range(query_db, user_id, target_start, target_end)
    # 最新快照日取全量(不受区间限制):判断快照是否滞后要用它,区间内的 sampleDates 只有最早 10 天
    latest_date = await DailySnapshotDao.get_latest_snapshot_date(query_db, user_id)

    by_date = defaultdict(int)
    for snapshot in snapshots:
        by_date[snapshot.snapshot_date] += 1

    return ResponseUtil.success(data={
        'totalRecords': len(snapshots),
        'dateRange': {'start': target_start.isoformat(), 'end': target_end.isoformat()},
        'datesWithData': len(by_date),
        'latestDate': latest_date.isoformat() if latest_date else None,
        'sampleDates': [[d.isoformat(), count] for d, count in list(by_date.items())[:10]],
    })


@snapshot_controller.get(
    '/list',
    summary='快照明细列表接口',
    description='按日聚合分页返回快照(日期/基金数/市值合计/累计净投入)',
    response_model=PageResponseModel,
)
@ApiRateLimit(
    namespace='snapshot_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='快照列表查询过于频繁，请稍后再试',
)
@Log(title='持仓快照', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_snapshot_list(
    request: Request,
    page_query: Annotated[SnapshotPageQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """按日聚合分页返回快照明细。"""
    target_end = page_query.end_date or date.today()
    # start_date 缺省 = 不限起始,查全部历史(2026-10-12 取消 90 天默认限制)
    target_start = page_query.start_date
    result = await SnapshotService.get_snapshot_daily_page_services(
        query_db,
        request.app.state.redis,
        _current_user_id(),
        target_start,
        target_end,
        page_query.page_num,
        page_query.page_size,
    )
    return ResponseUtil.success(model_content=result)


@snapshot_controller.get(
    '/day/{snapshot_date}',
    summary='每日持仓明细接口',
    description='返回某日该用户每只基金的份额/净值/市值与占比(行点击抽屉数据源)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='snapshot_day',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='每日持仓明细查询过于频繁，请稍后再试',
)
@Log(title='持仓快照', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_snapshot_day_detail(
    snapshot_date: date,
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """某日的基金明细(与按日聚合列表同走懒补)。"""
    result = await SnapshotService.get_snapshot_day_detail_services(
        query_db, request.app.state.redis, _current_user_id(), snapshot_date
    )
    return ResponseUtil.success(data=result)


@snapshot_controller.get(
    '/quarterly',
    summary='季度持仓变化接口',
    description='返回近 8 个季度末的持仓快照(季度末常撞周末,取 ≤ 季度末的最近快照日)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='snapshot_quarterly',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='季度持仓查询过于频繁，请稍后再试',
)
@Log(title='持仓快照', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_quarterly_snapshots(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """近 8 季度末持仓(变化对比由前端按相邻季度计算)。"""
    result = await SnapshotService.get_quarterly_snapshots_services(
        query_db, request.app.state.redis, _current_user_id()
    )
    return ResponseUtil.success(data=result)


@snapshot_controller.post(
    '/rebuild',
    summary='重建快照接口',
    description='从交易表全量重建快照与现金流(清空后逐日重建到今天)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='snapshot_rebuild',
    limit=10,
    period=3600,
    scope='user',
    algorithm='sliding_window',
    message='快照重建过于频繁，请稍后再试',
)
@Log(title='持仓快照', business_type=BusinessType.OTHER, mode=LogMode.AROUND)
async def rebuild_snapshots(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """从交易表重建快照与现金流。"""
    result = await SnapshotService.rebuild_from_transactions_services(
        query_db, request.app.state.redis, _current_user_id()
    )
    return ResponseUtil.success(data=result)


@snapshot_controller.delete(
    '/all',
    summary='清空快照接口',
    description='三级:只清空快照与现金流(交易与持仓不动,可随时重新生成)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='snapshot_clear_all',
    limit=3,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='清空快照操作过于频繁，请稍后再试',
)
@Log(title='持仓快照', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def clear_all_snapshots(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """清空全部快照与现金流。"""
    result = await SnapshotService.delete_all_snapshots_services(query_db, _current_user_id())
    return ResponseUtil.success(msg='快照已清空', data=result)
