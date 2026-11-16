"""基金管理模块 DAO(数据访问层)。

核心约定:所有写操作只 flush 不 commit,事务由 Service 层统一控制。
"""

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.response import PageModel
from module_fund.entity.do.fund_do import Fund
from module_fund.entity.vo.fund_vo import FundPageQueryModel
from utils.page_util import PageUtil


class FundDao:
    """基金管理模块数据库操作层。"""

    # ==================== 读 ====================

    @classmethod
    async def get_fund_by_id(cls, db: AsyncSession, fund_id: int) -> Fund | None:
        """根据 fund_id 获取未删除基金。"""
        result = await db.execute(
            select(Fund).where(Fund.fund_id == fund_id, Fund.del_flag == '0')
        )
        return result.scalars().first()

    @classmethod
    async def get_fund_by_code(cls, db: AsyncSession, code: str) -> Fund | None:
        """根据基金代码获取未删除基金(唯一性校验/业务定位用)。"""
        result = await db.execute(
            select(Fund).where(Fund.code == code, Fund.del_flag == '0')
        )
        return result.scalars().first()

    @classmethod
    async def get_any_fund_by_code(cls, db: AsyncSession, code: str) -> Fund | None:
        """根据基金代码获取任意状态基金(含已删,唯一约束兜底用)。"""
        result = await db.execute(select(Fund).where(Fund.code == code))
        return result.scalars().first()

    @classmethod
    async def get_funds_by_codes(cls, db: AsyncSession, codes: list[str]) -> list[tuple[str, str]]:
        """按代码批量取 (code, name):截图导入解析名称时需要「用户自己的基金」,一次取完避免 N+1。"""
        if not codes:
            return []
        result = await db.execute(select(Fund.code, Fund.name).where(Fund.code.in_(codes), Fund.del_flag == '0'))
        return [(row.code, row.name) for row in result.all()]

    @classmethod
    async def search_funds_by_name(cls, db: AsyncSession, keyword: str, limit: int = 20) -> list[tuple[str, str]]:
        """按名称包含关系取 (code, name):截图里只有基金名、没有代码,靠它认代码(唯一命中才采用)。"""
        cleaned = (keyword or '').replace('%', '').replace('_', '')
        if not cleaned:
            return []
        result = await db.execute(
            select(Fund.code, Fund.name)
            .where(Fund.name.like(f'%{cleaned}%'), Fund.del_flag == '0')
            .order_by(Fund.code)
            .limit(limit)
        )
        return [(row.code, row.name) for row in result.all()]

    @classmethod
    async def get_fund_list(
        cls, db: AsyncSession, query_object: FundPageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict[str, Any]]:
        """根据查询参数获取基金分页列表。"""
        query = (
            select(Fund)
            .where(
                Fund.del_flag == '0',
                # 条件查询:参数非空才追加 where(动态 SQL)
                Fund.code.like(f'%{query_object.code}%') if query_object.code else True,
                Fund.name.like(f'%{query_object.name}%') if query_object.name else True,
                Fund.fund_type == query_object.fund_type if query_object.fund_type else True,
                Fund.status == query_object.status if query_object.status else True,
            )
            .order_by(Fund.fund_id)
        )
        return await PageUtil.paginate(db, query, query_object.page_num, query_object.page_size, is_page)

    @classmethod
    async def get_fund_types(cls, db: AsyncSession) -> list[str]:
        """获取库内现有基金类型(distinct,只取未删除且有值的,按名称升序)。

        供列表页类型筛选下拉使用:类型集合取自 AkShare 且会随同步增长,
        所以由库里实际存在的值聚合得出,不在前后端任何一方写死常量。
        """
        result = await db.execute(
            select(Fund.fund_type)
            .where(Fund.del_flag == '0', Fund.fund_type.isnot(None))
            .distinct()
            .order_by(Fund.fund_type)
        )
        return [row[0] for row in result.all() if row[0]]

    # ==================== 写(只 flush,事务由 Service 控制) ====================

    @classmethod
    async def add_fund_dao(cls, db: AsyncSession, fund: Fund) -> Fund:
        """新增基金(flush 回填自增主键)。"""
        db.add(fund)
        await db.flush()
        return fund

    @classmethod
    async def edit_fund_dao(cls, db: AsyncSession, fund: dict) -> None:
        """编辑基金(批量更新语法,dict 含 fund_id 作 where 条件)。"""
        await db.execute(update(Fund), [fund])

    @classmethod
    async def delete_fund_dao(cls, db: AsyncSession, fund_id: int, update_by: str | None, update_time) -> None:
        """逻辑删除基金(只更新 del_flag)。"""
        await db.execute(
            update(Fund)
            .where(Fund.fund_id == fund_id)
            .values(del_flag='2', update_by=update_by, update_time=update_time)
        )
