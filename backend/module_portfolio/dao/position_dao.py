"""持仓模块 DAO(数据访问层):持仓头表。

核心约定:所有写操作只 flush 不 commit,事务由 Service 层统一控制。
"""

from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.response import PageModel
from module_fund.entity.do.fund_do import Fund
from module_portfolio.entity.do.position_do import UserFundPosition
from utils.page_util import PageUtil


class PositionDao:
    """持仓头表数据库操作层。"""

    # ==================== 读 ====================

    @classmethod
    async def get_positions(cls, db: AsyncSession, user_id: int) -> list[UserFundPosition]:
        """获取用户全部 active 持仓(排除已删)。"""
        result = await db.execute(
            select(UserFundPosition)
            .where(UserFundPosition.user_id == user_id, UserFundPosition.del_flag == '0')
            .order_by(UserFundPosition.position_id)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_positions_page(
        cls,
        db: AsyncSession,
        user_id: int,
        page_num: int,
        page_size: int,
        status: str | None = None,
        keyword: str | None = None,
        is_page: bool = True,
    ) -> PageModel | list[dict]:
        """分页获取用户 active 持仓头表(明细由 Service 逐条组装,这里只定位行与总数)。"""
        query = (
            select(UserFundPosition)
            .where(
                UserFundPosition.user_id == user_id,
                UserFundPosition.del_flag == '0',
                # 状态精确匹配由前端筛选 Tabs 下发,不传即不过滤
                UserFundPosition.status == status if status else True,
            )
            .order_by(UserFundPosition.position_id)
        )
        if keyword:
            # 名称在 fund 表(头表只存 code),join 一对一关联不产生重复行;
            # 名称/代码双字段模糊,任一命中即可
            query = query.join(Fund, UserFundPosition.fund_code == Fund.code).where(
                or_(
                    Fund.name.ilike(f'%{keyword}%'),
                    UserFundPosition.fund_code.ilike(f'%{keyword}%'),
                )
            )
        return await PageUtil.paginate(db, query, page_num, page_size, is_page=is_page)

    @classmethod
    async def get_all_positions(cls, db: AsyncSession, user_id: int) -> list[UserFundPosition]:
        """获取用户全部持仓(含已删——历史快照/现金流重建需反映当时状态)。"""
        result = await db.execute(
            select(UserFundPosition)
            .where(UserFundPosition.user_id == user_id)
            .order_by(UserFundPosition.position_id)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_position_by_id(
        cls, db: AsyncSession, position_id: int, user_id: int
    ) -> UserFundPosition | None:
        """获取单个 active 持仓(含行级归属校验)。"""
        result = await db.execute(
            select(UserFundPosition).where(
                UserFundPosition.position_id == position_id,
                UserFundPosition.user_id == user_id,
                UserFundPosition.del_flag == '0',
            )
        )
        return result.scalars().first()

    @classmethod
    async def get_active_position_by_fund(
        cls, db: AsyncSession, user_id: int, fund_code: str
    ) -> UserFundPosition | None:
        """按用户+基金定位 active 持仓(买入/赎回自动匹配用)。"""
        result = await db.execute(
            select(UserFundPosition).where(
                UserFundPosition.user_id == user_id,
                UserFundPosition.fund_code == fund_code,
                UserFundPosition.del_flag == '0',
            )
        )
        return result.scalars().first()

    @classmethod
    async def count_positions_by_fund_code(cls, db: AsyncSession, fund_code: str) -> int:
        """统计基金的持仓引用数(基金删除前保护检查,含已删持仓)。"""
        result = await db.execute(
            select(func.count()).select_from(UserFundPosition).where(UserFundPosition.fund_code == fund_code)
        )
        return result.scalar() or 0

    # ==================== 写(只 flush,事务由 Service 控制) ====================

    @classmethod
    async def add_position_dao(cls, db: AsyncSession, position: UserFundPosition) -> UserFundPosition:
        """新增持仓(flush 回填自增主键)。"""
        db.add(position)
        await db.flush()
        return position

    @classmethod
    async def delete_position_dao(
        cls, db: AsyncSession, position_id: int, update_by: str | None, update_time: datetime | None
    ) -> None:
        """软删除持仓(只更新 del_flag)。"""
        await db.execute(
            update(UserFundPosition)
            .where(UserFundPosition.position_id == position_id)
            .values(del_flag='2', update_by=update_by, update_time=update_time)
        )

    @classmethod
    async def get_any_position_by_id(
        cls, db: AsyncSession, position_id: int, user_id: int
    ) -> UserFundPosition | None:
        """获取持仓(不过滤 del_flag,含行级归属校验)。

        删除交易记录时需要看见软删持仓:记录删光要物理清掉空壳,
        删掉赎回记录使剩余份额回到正数时要把软删持仓复活。
        """
        result = await db.execute(
            select(UserFundPosition).where(
                UserFundPosition.position_id == position_id,
                UserFundPosition.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @classmethod
    async def revive_position_dao(cls, db: AsyncSession, position_id: int) -> None:
        """复活软删持仓(del_flag 置回 '0'):删除赎回记录后剩余份额回到正数。"""
        await db.execute(
            update(UserFundPosition)
            .where(UserFundPosition.position_id == position_id)
            .values(del_flag='0')
        )

    @classmethod
    async def delete_position_physical_dao(cls, db: AsyncSession, position: UserFundPosition) -> None:
        """物理删除单条持仓(记录删光后的空壳清理)。"""
        await db.delete(position)

    @classmethod
    async def delete_all_positions_for_user(cls, db: AsyncSession, user_id: int) -> int:
        """物理删除用户全部持仓(交易导入确认全量重建、级联清空持仓两处复用)。"""
        result = await db.execute(delete(UserFundPosition).where(UserFundPosition.user_id == user_id))
        return result.rowcount or 0
