"""交易明细多格式导入 Controller(API 路由层)。

支持 Excel(.xlsx)、PDF(文本层与扫描/图片页)、截图(PNG/JPEG);平台差异由项目根目录的
YAML 适配器描述(新增平台只加一份 YAML,不改代码)。preview / confirm 两段式:
先看解析结果与分级问题,确认后才落库(有 error 级问题直接拒绝)。
全域仅登录(行级隔离私域数据,不做按钮级权限,同 position_controller 头注)。
"""

from typing import Annotated

from fastapi import Depends, File, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.security import CurrentUser
from db.get_db import get_db
from module_portfolio.entity.vo.excel_vo import TransactionConfirmModel
from module_portfolio.service.excel_service import ExcelService
from module_portfolio.service.statement_import_service import StatementImportService
from module_portfolio.service.statement_readers import MIME_XLSX
from utils.response_util import ResponseUtil


import_controller = APIRouterPro(
    prefix='/portfolio/import',
    order_num=23,
    tags=['交易明细导入'],
)


def _current_user_id() -> int:
    """从上下文取当前用户 ID(鉴权依赖已保证登录)。"""
    current = get_current_user_or_none()
    if current is None:
        return 0
    return current.user_id


@import_controller.post(
    '/transactions/preview',
    summary='预览交易明细导入接口',
    description='解析 Excel/PDF/截图 交易明细(不落库),返回预览、统计与分级问题(文件类型按内容识别,不看扩展名)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='import_preview',
    limit=12,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='导入预览过于频繁，请稍后再试',
)
@Log(title='交易明细导入', business_type=BusinessType.IMPORT, mode=LogMode.AROUND)
async def preview_transaction_import(
    request: Request,
    file: Annotated[UploadFile, File(description='交易明细文件（.xlsx / PDF / PNG / JPEG）')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """预览交易明细导入结果。"""
    content = await file.read()
    result = await StatementImportService.preview_transaction_import_services(
        query_db, request.app.state.redis, _current_user_id(), content, file.filename or ''
    )
    return ResponseUtil.success(data=result)


@import_controller.post(
    '/transactions/confirm',
    summary='确认导入交易明细接口',
    description='导入数据与原始手输数据合并后全量重建持仓，并补一次快照重建；存在 error 级校验问题时拒绝落库',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='import_confirm',
    limit=10,
    period=300,
    scope='user',
    algorithm='sliding_window',
    message='导入确认操作过于频繁，请稍后再试',
)
@Log(title='交易明细导入', business_type=BusinessType.IMPORT, mode=LogMode.AROUND)
async def confirm_transaction_import(
    request: Request,
    confirm_info: TransactionConfirmModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> Response:
    """确认导入交易记录。"""
    result = await StatementImportService.confirm_transaction_import_services(
        query_db, request.app.state.redis, _current_user_id(), confirm_info
    )
    return ResponseUtil.success(data=result)


@import_controller.get(
    '/transactions/template',
    summary='下载交易记录导入模板接口',
    description='用解析器支持的语义表头生成 Excel 模板(含填写说明与示例行),用户按模板填写后可走 preview/confirm 导入',
)
@Log(title='交易明细导入', business_type=BusinessType.EXPORT, mode=LogMode.AROUND)
async def download_import_template(request: Request, current_user: CurrentUser) -> Response:
    """下载交易记录导入模板(xlsx 文件流;表头由适配器配置生成,与解析器同源)。

    request 只给 @Log 用:它用 isinstance 从实参里找 Request,漏写会直接 500。
    """
    file_content = await ExcelService.export_import_template_services()
    # 文件名给 ASCII:中文名由前端落盘时指定,免得依赖各浏览器对 filename* 的支持差异
    return ResponseUtil.streaming(
        data=iter([file_content]),
        headers={'Content-Disposition': 'attachment; filename=import-template.xlsx'},
        media_type=MIME_XLSX,
    )
