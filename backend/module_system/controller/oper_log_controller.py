"""操作日志模块 Controller（API 路由层）。

list 查询(按 category 分流) + 批量物理删除(2026-08-30 落地)。
查询挂 @Log(QUERY);**不挂 @ApiCache**(日志持续写入,缓存 TTL 期间新记录不可见)。
删除挂 @Log(DELETE)——删日志留审计痕迹(谁删的)本身就是目的。
"""

from typing import Annotated

from fastapi import Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.router import APIRouterPro
from common.response import PageResponseModel
from core.interface_auth import CheckUserInterfaceAuth
from db.get_db import get_db
from exceptions.exceptions import ServiceWarning
from module_system.entity.vo.oper_log_vo import OperLogDeleteModel, OperLogQueryModel
from module_system.service.oper_log_service import OperLogService
from utils.log import logger
from utils.response_util import ResponseUtil

# 创建路由器：prefix 统一前缀，order_num 控制注册顺序，tags 用于 Swagger 分组
oper_log_controller = APIRouterPro(
    prefix='/system/log',
    order_num=5,
    tags=['系统管理-日志管理'],
)


@oper_log_controller.get(
    '/list',
    summary='获取日志分页列表接口',
    description='按 category 分流查询操作/登录日志,支持标题/操作人/状态/时间范围过滤',
    response_model=PageResponseModel,
)
@ApiRateLimit(
    namespace='log_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='日志查询过于频繁，请稍后再试',
)
@Log(title='日志管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_system_log_list(
    request: Request,
    log_query: Annotated[OperLogQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:log:list')] = None,  # ← 放最后
) -> Response:
    """获取日志分页列表(操作/登录日志按 category 分流)。"""
    log_query_result = await OperLogService.get_oper_log_list_services(
        query_db, log_query, is_page=True
    )
    logger.info(
        f'[日志] 列表查询成功 category={log_query.category} '
        f'page={log_query.page_num} size={log_query.page_size}'
    )
    return ResponseUtil.success(model_content=log_query_result)


@oper_log_controller.get(
    '/{oper_id}',
    summary='获取日志详情接口',
    description='按 ID 查单条日志全量(含请求参数/返回结果大字段;列表接口已窄字段化,详情唯一全量出口)',
)
@ApiRateLimit(
    namespace='log_detail',
    limit=20,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='日志详情查询过于频繁，请稍后再试',
)
@Log(title='日志管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_oper_log_detail(
    request: Request,
    oper_id: Annotated[int, Path(description='日志 ID')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:log:query')] = None,  # ← 放最后
) -> Response:
    """查单条日志详情(admin 通配放行;common 无此 perm → 403)。"""
    detail = await OperLogService.get_oper_log_detail_services(query_db, oper_id)
    if detail is None:
        # 走统一异常处理(601 语义,前端 warning toast)
        raise ServiceWarning(message=f'日志不存在: oper_id={oper_id}')
    return ResponseUtil.success(model_content=detail)


@oper_log_controller.delete(
    '/{oper_ids}',
    summary='删除日志接口',
    description='批量物理删除操作/登录日志(逗号分隔 ID 串,无 del_flag 不可恢复)',
)
@ApiRateLimit(
    namespace='log_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除日志操作过于频繁，请稍后再试',
)
@Log(title='日志管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_oper_log(
    request: Request,
    oper_ids: Annotated[str, Path(description='需要删除的日志ID串(逗号分隔)')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:log:remove')] = None,  # ← 放最后
) -> Response:
    """批量物理删除日志(admin 通配放行;common 无此 perm → 403)。"""
    delete_result = await OperLogService.delete_oper_log_services(
        query_db, OperLogDeleteModel(operIds=oper_ids)
    )
    return ResponseUtil.success(msg=delete_result.message)
