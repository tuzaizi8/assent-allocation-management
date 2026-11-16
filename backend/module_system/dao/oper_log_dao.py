"""操作日志模块 DAO（数据访问层）。

查询 + 批量物理删除(sys_oper_log 无 del_flag,对齐 sys_menu 物理删模式);
常规写入由 @Log 注解 + 后台队列完成(见 oper_log_service)。

核心约定：只读操作无需事务控制，直接查询。

2026-08-30 慢查询优化:列表查询改**窄字段投影**——oper_param/json_result/error_msg
三个大字段不进列表(json_result 实测最大 7 亿字符,SELECT * 会整行物化导致秒级慢查询
与 DataGrip JVM 飙升);详情走 get_oper_log_by_id 单查全量。
"""

from datetime import datetime, time
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.response import PageModel
from module_system.entity.do.oper_log_do import SysOperLog
from module_system.entity.vo.oper_log_vo import OperLogQueryModel
from utils.page_util import PageUtil

# 列表页窄字段集(UI 只消费这些;大字段 oper_param/json_result/error_msg 排除)
LOG_LIST_COLUMNS = (
    SysOperLog.oper_id,
    SysOperLog.title,
    SysOperLog.business_type,
    SysOperLog.method,
    SysOperLog.request_method,
    SysOperLog.oper_name,
    SysOperLog.dept_name,
    SysOperLog.oper_url,
    SysOperLog.oper_ip,
    SysOperLog.status,
    SysOperLog.cost_time,
    SysOperLog.oper_time,
    SysOperLog.category,
)


class OperLogDao:
    """操作日志模块数据库操作层。"""

    @classmethod
    async def get_oper_log_list(
        cls,
        db: AsyncSession,
        query_object: OperLogQueryModel,
        is_page: bool = False,
    ) -> PageModel | list[dict[str, Any]]:
        """根据查询参数获取操作日志分页列表。

        :param db: orm 对象
        :param query_object: 查询参数对象(category 必过滤,分流操作/登录日志)
        :param is_page: 是否开启分页
        :return: 日志分页列表信息对象
        """
        # 窄字段投影(见模块头注释):select(*LOG_LIST_COLUMNS) 而非 select(SysOperLog)
        query = (
            select(*LOG_LIST_COLUMNS)
            .where(
                # category 必过滤(单页双 Tab 的服务端分流锚点)
                SysOperLog.category == query_object.category,
                # 条件查询：只有参数非空时才追加 where 条件（动态 SQL,对齐 user_dao 范式）
                SysOperLog.title.like(f'%{query_object.title}%') if query_object.title else True,
                SysOperLog.oper_name.like(f'%{query_object.oper_name}%') if query_object.oper_name else True,
                SysOperLog.status == query_object.status if query_object.status is not None else True,
                # 时间范围查询(对齐 user_dao L141-147:字符串日期 → 当天首末时刻)
                SysOperLog.oper_time.between(
                    datetime.combine(datetime.strptime(query_object.begin_time, '%Y-%m-%d'), time(0, 0, 0)),
                    datetime.combine(datetime.strptime(query_object.end_time, '%Y-%m-%d'), time(23, 59, 59)),
                )
                if query_object.begin_time and query_object.end_time
                else True,
            )
            .order_by(SysOperLog.oper_id.desc())
            .distinct()
        )
        log_list: PageModel | list[dict[str, Any]] = await PageUtil.paginate(
            db, query, query_object.page_num, query_object.page_size, is_page
        )
        return log_list

    @classmethod
    async def get_oper_log_by_id(cls, db: AsyncSession, oper_id: int) -> SysOperLog | None:
        """按主键查单条日志全量(含 oper_param/json_result/error_msg 大字段)。

        :param db: orm 对象
        :param oper_id: 日志主键
        :return: DO 实体或 None
        """
        result = await db.execute(select(SysOperLog).where(SysOperLog.oper_id == oper_id))
        return result.scalars().first()

    @classmethod
    async def delete_oper_log_dao(cls, db: AsyncSession, oper_ids: list[int]) -> None:
        """批量物理删除日志(无 del_flag,直接 delete)。

        :param db: orm 对象
        :param oper_ids: 日志 ID 列表
        """
        await db.execute(delete(SysOperLog).where(SysOperLog.oper_id.in_(oper_ids)))
