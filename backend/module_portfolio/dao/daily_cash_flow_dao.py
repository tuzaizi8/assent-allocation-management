"""持仓模块 DAO(数据访问层):每日现金流水。"""

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from module_portfolio.entity.do.daily_cash_flow_do import DailyCashFlow


class DailyCashFlowDao:
    """每日现金流水数据库操作层。"""

    # ==================== 读 ====================

    @classmethod
    async def get_cash_flows_in_range(
        cls, db: AsyncSession, user_id: int, start_date: date, end_date: date
    ) -> list[DailyCashFlow]:
        """获取日期范围内的现金流水(按日期升序)。"""
        result = await db.execute(
            select(DailyCashFlow)
            .where(
                DailyCashFlow.user_id == user_id,
                DailyCashFlow.flow_date >= start_date,
                DailyCashFlow.flow_date <= end_date,
            )
            .order_by(DailyCashFlow.flow_date)
        )
        return list(result.scalars().all())

    # ==================== 写(只 flush,事务由 Service 控制) ====================

    @classmethod
    async def upsert_cash_flows_batch_dao(cls, db: AsyncSession, user_id: int, rows: list[dict]) -> None:
        """批量插入或更新现金流水:一次读回区间内既有行,按日期索引改属性或新增,最后单次 flush。

        同快照:虽有 (user_id, 日期) 唯一约束,逐行 SELECT + 写会让往返次数随时长线性增长,故保持
        一次载入后复用;并发安全由调用方(Service)在写入前抢的事务级互斥锁保证,唯一约束只作兜底。
        """
        if not rows:
            return
        dates = [row['flow_date'] for row in rows]
        result = await db.execute(
            select(DailyCashFlow).where(
                DailyCashFlow.user_id == user_id,
                DailyCashFlow.flow_date >= min(dates),
                DailyCashFlow.flow_date <= max(dates),
            )
        )
        existing = {row.flow_date: row for row in result.scalars().all()}
        for row in rows:
            matched = existing.get(row['flow_date'])
            if matched is None:
                db.add(DailyCashFlow(**row))
                continue
            matched.cash_flow = row['cash_flow']
            matched.cumulative_invested = row['cumulative_invested']
        await db.flush()

    @classmethod
    async def insert_cash_flows_bulk_dao(cls, db: AsyncSession, rows: list[dict]) -> None:
        """批量插入现金流水(调用方已清空该用户数据,无需查重)。"""
        if not rows:
            return
        db.add_all([DailyCashFlow(**row) for row in rows])
        await db.flush()

    @classmethod
    async def delete_all_cash_flows_for_user(cls, db: AsyncSession, user_id: int) -> int:
        """物理删除用户全部现金流(重建用)。"""
        result = await db.execute(delete(DailyCashFlow).where(DailyCashFlow.user_id == user_id))
        return result.rowcount or 0
