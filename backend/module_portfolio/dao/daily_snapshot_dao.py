"""持仓模块 DAO(数据访问层):每日持仓快照。"""

from collections import defaultdict
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.response import PageModel
from module_fund.entity.do.fund_do import Fund
from module_portfolio.entity.do.daily_cash_flow_do import DailyCashFlow
from module_portfolio.entity.do.daily_snapshot_do import DailyPortfolioSnapshot
from utils.page_util import PageUtil


class DailySnapshotDao:
    """每日持仓快照数据库操作层。"""

    # ==================== 读 ====================

    @classmethod
    async def get_snapshots_in_range(
        cls, db: AsyncSession, user_id: int, start_date: date, end_date: date
    ) -> list[DailyPortfolioSnapshot]:
        """获取日期范围内的快照(按日期升序)。"""
        result = await db.execute(
            select(DailyPortfolioSnapshot)
            .where(
                DailyPortfolioSnapshot.user_id == user_id,
                DailyPortfolioSnapshot.snapshot_date >= start_date,
                DailyPortfolioSnapshot.snapshot_date <= end_date,
            )
            .order_by(DailyPortfolioSnapshot.snapshot_date)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_latest_snapshot_date(cls, db: AsyncSession, user_id: int) -> date | None:
        """获取用户最新快照日期(交易后回填起点判定用)。"""
        result = await db.execute(
            select(DailyPortfolioSnapshot.snapshot_date)
            .where(DailyPortfolioSnapshot.user_id == user_id)
            .order_by(DailyPortfolioSnapshot.snapshot_date.desc())
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None

    @classmethod
    async def get_earliest_snapshot_date(cls, db: AsyncSession, user_id: int) -> date | None:
        """取用户最远快照日(季度变化卡片的序列起点判定)。"""
        result = await db.execute(
            select(func.min(DailyPortfolioSnapshot.snapshot_date)).where(
                DailyPortfolioSnapshot.user_id == user_id
            )
        )
        return result.scalar()

    @classmethod
    async def get_latest_snapshot_date_on_or_before(
        cls, db: AsyncSession, user_id: int, day: date
    ) -> date | None:
        """取 ≤ day 的最近快照日(季度末常撞周末/未生成,向后取最近有数据的一天)。"""
        result = await db.execute(
            select(func.max(DailyPortfolioSnapshot.snapshot_date)).where(
                DailyPortfolioSnapshot.user_id == user_id,
                DailyPortfolioSnapshot.snapshot_date <= day,
            )
        )
        return result.scalar()

    @classmethod
    async def get_snapshots_for_day(
        cls, db: AsyncSession, user_id: int, day: date
    ) -> list[dict]:
        """获取某日该用户全部快照行(join 基金名称,按市值降序)。

        每日持仓页行点击抽屉的数据源:聚合列表给的是「基金数」,这里是
        当日每只基金的具体行。名称走 join(fund 表按 code 逻辑关联)。
        """
        result = await db.execute(
            select(
                DailyPortfolioSnapshot.fund_code,
                Fund.name,
                Fund.fund_type,
                DailyPortfolioSnapshot.shares,
                DailyPortfolioSnapshot.nav,
                DailyPortfolioSnapshot.market_value,
            )
            .join(Fund, Fund.code == DailyPortfolioSnapshot.fund_code, isouter=True)
            .where(
                DailyPortfolioSnapshot.user_id == user_id,
                DailyPortfolioSnapshot.snapshot_date == day,
            )
            .order_by(DailyPortfolioSnapshot.market_value.desc())
        )
        return [
            {
                'fund_code': row.fund_code,
                'fund_name': row.name,
                'fund_type': row.fund_type,
                'shares': float(row.shares or 0),
                'nav': float(row.nav or 0),
                'market_value': float(row.market_value or 0),
            }
            for row in result.all()
        ]

    @classmethod
    async def get_snapshot_daily_page(
        cls,
        db: AsyncSession,
        user_id: int,
        start_date: date | None,
        end_date: date,
        page_num: int,
        page_size: int,
    ) -> PageModel:
        """按日聚合分页:日期 / 基金数 / 市值合计 / 同日累计净投入(新→旧)。

        start_date 为 None 时不限起始(查全部历史)——2026-10-12 起 90 天默认
        限制取消,历史持仓页直接全量分页。聚合列必须显式 label:CamelCaseUtil
        按键名转驼峰,未命名列会产出 sum(market_value) 这类非法键名;累计净投入
        取同日现金流行,无该行返回 null 交由前端显示破折号。
        """
        query = (
            select(
                DailyPortfolioSnapshot.snapshot_date.label('snapshot_date'),
                func.count(DailyPortfolioSnapshot.snapshot_id).label('fund_count'),
                func.sum(DailyPortfolioSnapshot.market_value).label('total_value'),
                select(DailyCashFlow.cumulative_invested)
                .where(
                    DailyCashFlow.user_id == user_id,
                    DailyCashFlow.flow_date == DailyPortfolioSnapshot.snapshot_date,
                )
                .scalar_subquery()
                .label('cumulative_invested'),
            )
            .where(
                DailyPortfolioSnapshot.user_id == user_id,
                DailyPortfolioSnapshot.snapshot_date <= end_date,
                *(
                    [DailyPortfolioSnapshot.snapshot_date >= start_date]
                    if start_date is not None
                    else []
                ),
            )
            .group_by(DailyPortfolioSnapshot.snapshot_date)
            .order_by(DailyPortfolioSnapshot.snapshot_date.desc())
        )
        return await PageUtil.paginate(db, query, page_num, page_size, is_page=True)

    # ==================== 写(只 flush,事务由 Service 控制) ====================

    @classmethod
    async def upsert_snapshots_batch_dao(cls, db: AsyncSession, user_id: int, rows: list[dict]) -> None:
        """批量插入或更新快照:一次读回区间内既有行,按 (日期, 基金) 索引改属性或新增,最后单次 flush。

        虽有 (user_id, 日期, 基金) 唯一约束可改走 ON CONFLICT,但逐行 SELECT + 写的往返次数会随
        「天数 × 基金数」线性增长,故保持「一次载入后复用」;并发安全由调用方(Service)在写入前
        抢的事务级互斥锁保证,唯一约束只作兜底。
        """
        if not rows:
            return
        dates = [row['snapshot_date'] for row in rows]
        result = await db.execute(
            select(DailyPortfolioSnapshot).where(
                DailyPortfolioSnapshot.user_id == user_id,
                DailyPortfolioSnapshot.snapshot_date >= min(dates),
                DailyPortfolioSnapshot.snapshot_date <= max(dates),
            )
        )
        existing = {(row.snapshot_date, row.fund_code): row for row in result.scalars().all()}
        for row in rows:
            matched = existing.get((row['snapshot_date'], row['fund_code']))
            if matched is None:
                db.add(DailyPortfolioSnapshot(**row))
                continue
            matched.shares = row['shares']
            matched.nav = row['nav']
            matched.market_value = row['market_value']
        await db.flush()

    @classmethod
    async def insert_snapshots_bulk_dao(cls, db: AsyncSession, rows: list[dict]) -> None:
        """批量插入快照(调用方已清空该用户数据,无需查重)。"""
        if not rows:
            return
        db.add_all([DailyPortfolioSnapshot(**row) for row in rows])
        await db.flush()

    @classmethod
    async def delete_all_snapshots_for_user(cls, db: AsyncSession, user_id: int) -> int:
        """物理删除用户全部快照(重建用)。"""
        result = await db.execute(
            delete(DailyPortfolioSnapshot).where(DailyPortfolioSnapshot.user_id == user_id)
        )
        return result.rowcount or 0

    @classmethod
    async def delete_snapshot_pairs_dao(
        cls, db: AsyncSession, user_id: int, pairs: list[tuple[date, str]]
    ) -> int:
        """按 (日期, 基金) 定向删除快照行:区间增量补数时清掉「份额已归零」的残留行。

        只删入参里明确给出的组合(调用方按交易流水判定份额<=0 才纳入),取不到净值而没算出来的行
        不在入参里,绝不会被误删;按日期分组删,往返次数只取决于区间天数(通常 1~3 天),
        不随历史长度增长。
        """
        if not pairs:
            return 0
        codes_by_date: dict[date, list[str]] = defaultdict(list)
        for snapshot_date, fund_code in pairs:
            codes_by_date[snapshot_date].append(fund_code)
        deleted = 0
        for snapshot_date, fund_codes in codes_by_date.items():
            result = await db.execute(
                delete(DailyPortfolioSnapshot).where(
                    DailyPortfolioSnapshot.user_id == user_id,
                    DailyPortfolioSnapshot.snapshot_date == snapshot_date,
                    DailyPortfolioSnapshot.fund_code.in_(fund_codes),
                )
            )
            deleted += result.rowcount or 0
        return deleted
