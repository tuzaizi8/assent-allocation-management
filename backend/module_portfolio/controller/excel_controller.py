"""持仓 Excel 导出 Controller(API 路由层)。

只保留持仓导出(文件流);交易明细导入已迁至 `/portfolio/import/*`
(见 import_controller:Excel / PDF / 截图 + 平台适配 YAML + 分级校验)。
全域仅登录(行级隔离私域数据,不做按钮级权限,同 position_controller 头注)。
"""

from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.security import CurrentUser
from db.get_db import get_db
from module_portfolio.service.excel_service import ExcelService
from module_portfolio.service.position_service import PositionService
from utils.response_util import ResponseUtil

EXCEL_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


excel_controller = APIRouterPro(
    prefix='/portfolio/excel',
    order_num=23,
    tags=['持仓导出'],
)


def _current_user_id() -> int:
    """从上下文取当前用户 ID(鉴权依赖已保证登录)。"""
    current = get_current_user_or_none()
    if current is None:
        return 0
    return current.user_id


@excel_controller.get(
    '/export',
    summary='导出持仓接口',
    description='导出当前用户持仓明细为 Excel 文件流',
)
@Log(title='持仓导入导出', business_type=BusinessType.EXPORT, mode=LogMode.AROUND)
async def export_portfolio(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """导出持仓数据到 Excel。"""
    overview = await PositionService.get_overview_services(
        query_db, request.app.state.redis, _current_user_id()
    )
    file_content = await ExcelService.export_portfolio_services(overview['positions'])
    return ResponseUtil.streaming(
        data=iter([file_content]),
        headers={'Content-Disposition': 'attachment; filename=portfolio.xlsx'},
        media_type=EXCEL_MEDIA_TYPE,
    )


@excel_controller.get(
    '/transactions',
    summary='导出交易记录接口',
    description='导出当前用户全部交易记录为 Excel(与导入模板同列形,可直接回导)',
)
@ApiRateLimit(
    namespace='excel_tx_export',
    limit=6,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='导出操作过于频繁，请稍后再试',
)
@Log(title='持仓导入导出', business_type=BusinessType.EXPORT, mode=LogMode.AROUND)
async def export_transactions(
    request: Request,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """导出交易记录到 Excel(列形与导入模板一致,支持再导入)。"""
    rows = await PositionService.get_all_transactions_services(query_db, _current_user_id())
    file_content = await ExcelService.export_transactions_services(rows)
    return ResponseUtil.streaming(
        data=iter([file_content]),
        headers={'Content-Disposition': 'attachment; filename=transactions.xlsx'},
        media_type=EXCEL_MEDIA_TYPE,
    )

