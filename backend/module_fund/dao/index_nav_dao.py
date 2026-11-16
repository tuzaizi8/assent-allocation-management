"""指数净值历史 DAO(数据访问层)。

一行一个指数,nav_data 存完整历史行情,时间范围过滤由 ChartService 负责。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from module_fund.entity.do.index_nav_do import IndexNavHistory
from utils.nav_window_util import window_start


class IndexNavDao:
    """指数净值历史数据库操作层。"""

    @classmethod
    async def get_nav_history(cls, db: AsyncSession, index_code: str) -> Optional[list[dict]]:
        """获取指数行情记录列表(nav_data.records),未命中返回 None。"""
        result = await db.execute(select(IndexNavHistory).where(IndexNavHistory.index_code == index_code))
        record = result.scalars().first()
        if record and record.nav_data and 'records' in record.nav_data:
            return record.nav_data['records']
        return None

    @classmethod
    async def list_all(cls, db: AsyncSession) -> list[IndexNavHistory]:
        """返回全部指数行情缓存行(供 Service 与内置指数清单合并派生汇总)。"""
        result = await db.execute(select(IndexNavHistory))
        return list(result.scalars().all())

    @classmethod
    async def delete_by_codes(cls, db: AsyncSession, index_codes: list[str]) -> int:
        """按指数代码物理删除缓存行(清缓存,重新同步/访问图表即重拉)。"""
        result = await db.execute(
            delete(IndexNavHistory).where(IndexNavHistory.index_code.in_(index_codes))
        )
        return result.rowcount

    @classmethod
    async def get_by_code(cls, db: AsyncSession, index_code: str) -> IndexNavHistory | None:
        """按指数代码取缓存行(含 update_time 等元数据)。"""
        result = await db.execute(select(IndexNavHistory).where(IndexNavHistory.index_code == index_code))
        return result.scalars().first()

    @classmethod
    async def upsert_nav_history(
        cls, db: AsyncSession, index_code: str, index_name: str, records: list[dict], source: str = 'akshare'
    ) -> None:
        """写入或更新指数行情(只 flush,事务由调用方 Service 控制)。"""
        nav_data = {'source': source, 'records': records}
        result = await db.execute(select(IndexNavHistory).where(IndexNavHistory.index_code == index_code))
        existing = result.scalars().first()
        if existing:
            existing.nav_data = nav_data
            existing.index_name = index_name
            # 显式刷新同步时间:数据未变也算"同步过"。SQLAlchemy 2.0 flush 按净变化判定,
            # 行情等值时 nav_data 赋值会被吞掉(不发 UPDATE),onupdate 失效 → 更新时间冻结
            existing.update_time = datetime.now()
        else:
            db.add(IndexNavHistory(index_code=index_code, index_name=index_name, nav_data=nav_data))
        await db.flush()

    @staticmethod
    def is_stale_records(
        records: list[dict], update_time: datetime | None, now: datetime | None = None
    ) -> bool:
        """判定行情记录是否过期(纯函数,供 is_nav_stale 与同步状态三态共用)。

        规则(双窗口失效,与基金净值同口径):最新记录日 ≥ 今天 → 新鲜;
        否则 update_time 在当前窗口起点(00:00/22:00)之后 → 新鲜,过期。
        records 为空/缺失最新日期 → 视为过期(无数据无从谈新鲜)。
        now 可注入以便测试跨 22 点窗口的两种场景。
        """
        if not records:
            return True
        latest_date_str = records[-1].get('nav_date')
        if not latest_date_str:
            return True
        try:
            latest_date = datetime.strptime(str(latest_date_str), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return True
        current = now or datetime.now()
        if latest_date >= current.date():
            return False
        if update_time is None:
            return True
        return update_time < window_start(current)

    @classmethod
    async def is_nav_stale(cls, db: AsyncSession, index_code: str) -> bool:
        """判断指数行情是否过期(双窗口,与基金净值同口径,见 utils/nav_window_util)。"""
        result = await db.execute(select(IndexNavHistory).where(IndexNavHistory.index_code == index_code))
        record = result.scalars().first()
        if not record or not record.nav_data or 'records' not in record.nav_data:
            return True
        return cls.is_stale_records(record.nav_data['records'], record.update_time)
