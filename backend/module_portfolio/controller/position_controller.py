"""持仓管理模块 Controller(API 路由层)。

路由经 APIRouterPro 自动注册;user_id 一律取当前登录用户上下文(行级隔离)。
全域仅登录不挂按钮级权限:持仓是行级隔离的私域数据,接口只可能操作到
当前用户自己的账本,权限校验无安全意义只构成"登录即用"的障碍。
"""

from typing import Annotated

from fastapi import BackgroundTasks, Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel, PageResponseModel
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.security import CurrentUser
from db.get_db import get_db
from exceptions.exceptions import ServiceWarning
from module_portfolio.entity.vo.position_vo import (
    PortfolioRuleModel,
    PositionCreateModel,
    PositionPageQueryModel,
    PurchaseRecordCreateModel,
    RedemptionRecordCreateModel,
    TransactionPageQueryModel,
)
from module_portfolio.service.portfolio_rule_service import PortfolioRuleService
from module_portfolio.service.position_service import PositionService
from module_portfolio.service.statement_import_service import StatementImportService
from module_portfolio.service.snapshot_service import rebuild_snapshots_in_background
from utils.response_util import ResponseUtil


position_controller = APIRouterPro(
    prefix='/portfolio/position',
    order_num=20,
    tags=['持仓管理'],
)


def _current_user_id() -> int:
    """从上下文取当前用户 ID(鉴权依赖已保证登录)。"""
    current = get_current_user_or_none()
    if current is None:
        return 0
    return current.user_id


@position_controller.get(
    '/list',
    summary='获取持仓列表接口',
    description='分页返回当前用户有效持仓(含汇总市值/盈亏与买卖历史)',
    response_model=PageResponseModel,
)
@ApiRateLimit(
    namespace='position_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='持仓查询过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_positions(
    request: Request,
    page_query: Annotated[PositionPageQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """获取持仓列表(分页;isPage=false 返回全量,简况卡片页消费)。"""
    page_result = await PositionService.get_positions_services(
        query_db,
        request.app.state.redis,
        _current_user_id(),
        page_query.page_num,
        page_query.page_size,
        is_page=page_query.is_page,
        status=page_query.status,
        keyword=page_query.keyword,
        sort_by=page_query.sort_by,
        sort_order=page_query.sort_order,
    )
    # model_content 仅接受 Pydantic 模型(内部调 model_dump),is_page=False 的
    # 全量 list 必须走 rows 通道,响应形状与 rows 型接口一致(顶层 rows 无 data 键)
    if page_query.is_page:
        return ResponseUtil.success(model_content=page_result)
    return ResponseUtil.success(rows=page_result)


@position_controller.get(
    '/transactions',
    summary='获取交易记录接口',
    description='分页返回当前用户买入/赎回交易记录(按日期倒序)',
    response_model=PageResponseModel,
)
@ApiRateLimit(
    namespace='position_transactions',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='交易记录查询过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_transactions(
    request: Request,
    page_query: Annotated[TransactionPageQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """获取交易记录(分页)。"""
    page_result = await PositionService.get_transactions_services(
        query_db,
        _current_user_id(),
        page_query.page_num,
        page_query.page_size,
        tx_type=page_query.tx_type,
    )
    return ResponseUtil.success(model_content=page_result)


@position_controller.get(
    '/rules',
    summary='获取分散度规则接口',
    description='返回当前用户分散度规则(无记录返回默认值)',
    response_model=DataResponseModel,
)
@Log(title='持仓管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_rules(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """获取分散度规则。"""
    rules = await PortfolioRuleService.get_rules_services(query_db, _current_user_id())
    return ResponseUtil.success(data=rules.model_dump(by_alias=True))


@position_controller.get(
    '/{position_id}',
    summary='获取持仓明细接口',
    description='返回持仓明细(含买卖历史,行级归属校验)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='position_detail',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='持仓查询过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_position_detail(
    request: Request,
    position_id: Annotated[int, Path(description='持仓ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """获取持仓明细。"""
    detail = await PositionService.get_position_detail_services(
        query_db, request.app.state.redis, position_id, _current_user_id()
    )
    if detail is None:
        raise ServiceWarning(message='持仓不存在')
    return ResponseUtil.success(data=detail)


@position_controller.post(
    '',
    summary='创建持仓接口',
    description='首次买入建仓(份额按购买金额/买入日净值自动换算,重复建仓拒绝)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='position_add',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='创建持仓操作过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def create_position(
    request: Request,
    position_info: PositionCreateModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """创建持仓(首次买入)。"""
    detail = await PositionService.create_position_services(
        query_db, request.app.state.redis, _current_user_id(), position_info
    )
    return ResponseUtil.success(msg='创建成功', data=detail)


@position_controller.post(
    '/purchase',
    summary='分批买入接口',
    description='追加买入(无有效持仓时自动建仓,份额按金额/当日净值换算)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='position_purchase',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='买入操作过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def add_purchase(
    request: Request,
    purchase_info: PurchaseRecordCreateModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """分批买入。"""
    record = await PositionService.add_purchase_services(
        query_db, request.app.state.redis, _current_user_id(), purchase_info
    )
    return ResponseUtil.success(msg='买入成功', data=record)


@position_controller.post(
    '/redeem',
    summary='赎回接口',
    description='部分/全部赎回(净值按赎回日自动获取,全额赎回自动软删持仓)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='position_redeem',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='赎回操作过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def redeem_position(
    request: Request,
    redemption_info: RedemptionRecordCreateModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """赎回持仓。"""
    record = await PositionService.add_redemption_services(
        query_db, request.app.state.redis, _current_user_id(), redemption_info
    )
    return ResponseUtil.success(msg='赎回成功', data=record)


# 两个「全部清空」必须注册在 '/{position_id}' 之前:否则 '/all' 会被路径参数
# 当作 position_id 抢先匹配,int 校验失败直接 422
@position_controller.delete(
    '/transactions',
    summary='清空交易记录接口',
    description='一级:物理清空全部买卖流水,连带清空持仓与快照/现金流(不可恢复)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='position_clear_transactions',
    limit=3,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='清空交易记录操作过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def clear_all_transactions(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """清空全部交易记录(级联清空持仓与快照/现金流)。"""
    result = await PositionService.delete_all_transactions_services(query_db, _current_user_id())
    return ResponseUtil.success(msg='交易记录已清空', data=result)


@position_controller.delete(
    '/all',
    summary='清空持仓接口',
    description='二级:物理清空全部持仓,连带清空快照/现金流(买卖流水保留)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='position_clear_all',
    limit=3,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='清空持仓操作过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def clear_all_positions(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """清空全部持仓(级联清空快照/现金流)。"""
    result = await PositionService.delete_all_positions_services(query_db, _current_user_id())
    return ResponseUtil.success(msg='持仓已清空', data=result)


@position_controller.post(
    '/rebuild-from-transactions',
    summary='重建持仓接口',
    description='从交易记录全量重建持仓头表(头表清空重放,记录份额金额不变,'
    'position_id 重挂;二级清空后流水悬空的修复入口)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='position_rebuild',
    limit=3,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='重建持仓操作过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def rebuild_positions(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """从交易记录重建持仓(头表全量重放,流水不动)。"""
    result = await StatementImportService.rebuild_positions_services(
        query_db, request.app.state.redis, _current_user_id()
    )
    return ResponseUtil.success(msg='持仓已重建', data=result)


@position_controller.delete(
    '/transactions/purchase/{record_id}',
    summary='删除买入记录接口',
    description='单条硬删除买入记录(连带快照全量重建;记录删光则清理持仓空壳)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='position_tx_delete',
    limit=10,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='删除交易记录操作过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_purchase_record(
    request: Request,
    background_tasks: BackgroundTasks,
    record_id: Annotated[int, Path(description='买入记录ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """删除单条买入记录(硬删除)。"""
    deleted = await PositionService.delete_transaction_services(
        query_db, _current_user_id(), 'purchase', record_id
    )
    if deleted:
        # 快照重建放后台:全量重建实测 5~98 秒,同步会拖住响应诱发重复点击
        background_tasks.add_task(
            rebuild_snapshots_in_background, _current_user_id(), request.app.state.redis
        )
    return ResponseUtil.success(msg='删除成功')


@position_controller.delete(
    '/transactions/redemption/{record_id}',
    summary='删除赎回记录接口',
    description='单条硬删除赎回记录(连带快照全量重建;剩余份额回正则复活软删持仓)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='position_tx_delete',
    limit=10,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='删除交易记录操作过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_redemption_record(
    request: Request,
    background_tasks: BackgroundTasks,
    record_id: Annotated[int, Path(description='赎回记录ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """删除单条赎回记录(硬删除)。"""
    deleted = await PositionService.delete_transaction_services(
        query_db, _current_user_id(), 'redemption', record_id
    )
    if deleted:
        background_tasks.add_task(
            rebuild_snapshots_in_background, _current_user_id(), request.app.state.redis
        )
    return ResponseUtil.success(msg='删除成功')


@position_controller.delete(
    '/{position_id}',
    summary='删除持仓接口',
    description='手动软删除持仓(交易记录保留)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='position_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除持仓操作过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_position(
    request: Request,
    position_id: Annotated[int, Path(description='持仓ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """删除持仓(软删除)。"""
    await PositionService.delete_position_services(query_db, position_id, _current_user_id())
    return ResponseUtil.success(msg='删除成功')


@position_controller.put(
    '/rules',
    summary='更新分散度规则接口',
    description='创建或更新当前用户分散度规则',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='rule_update',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='规则修改过于频繁，请稍后再试',
)
@Log(title='持仓管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def update_rules(
    request: Request,
    rules: PortfolioRuleModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """更新分散度规则。"""
    result = await PortfolioRuleService.update_rules_services(query_db, _current_user_id(), rules)
    return ResponseUtil.success(msg=result.message)
