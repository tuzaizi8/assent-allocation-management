"""资产配置模块 DAO(数据访问层):基金映射。

核心约定:所有写操作只 flush 不 commit,事务由 Service 层统一控制。
"""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from module_asset.entity.do.asset_class_do import FundAssetMapping
from module_fund.entity.do.fund_do import Fund
from module_portfolio.entity.do.position_do import UserFundPosition


class FundMappingDao:
    """基金映射数据库操作层。"""

    @classmethod
    async def get_fund_mappings(cls, db: AsyncSession, user_id: int) -> list[FundAssetMapping]:
        """获取用户全部基金映射。"""
        result = await db.execute(
            select(FundAssetMapping).where(FundAssetMapping.user_id == user_id)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_mapping_by_fund(
        cls, db: AsyncSession, user_id: int, fund_id: int
    ) -> FundAssetMapping | None:
        """获取指定基金的映射(upsert 定位用)。"""
        result = await db.execute(
            select(FundAssetMapping).where(
                FundAssetMapping.user_id == user_id,
                FundAssetMapping.fund_id == fund_id,
            )
        )
        return result.scalars().first()

    @classmethod
    async def add_mapping_dao(cls, db: AsyncSession, mapping: FundAssetMapping) -> FundAssetMapping:
        """新增映射(flush 回填自增主键)。"""
        db.add(mapping)
        await db.flush()
        return mapping

    @classmethod
    async def delete_mapping_by_fund(cls, db: AsyncSession, user_id: int, fund_id: int) -> int:
        """删除指定基金的映射,返回删除行数。"""
        result = await db.execute(
            delete(FundAssetMapping).where(
                FundAssetMapping.user_id == user_id,
                FundAssetMapping.fund_id == fund_id,
            )
        )
        return result.rowcount or 0

    @classmethod
    async def count_mappings_by_asset_class(cls, db: AsyncSession, asset_class_id: int) -> int:
        """统计资产类别的映射引用数(类别删除前保护检查)。"""
        result = await db.execute(
            select(func.count())
            .select_from(FundAssetMapping)
            .where(FundAssetMapping.asset_class_id == asset_class_id)
        )
        return result.scalar() or 0

    @classmethod
    async def get_unmapped_funds(cls, db: AsyncSession, user_id: int) -> list[Fund]:
        """获取用户持仓中尚未映射的基金(取 active 持仓基金 - 已映射基金)。

        持仓头表只存 fund_code、映射表只存 fund_id,故先按 code 取到基金实体再比对,
        不做「拿 code 当 id 用」的跨表混用。
        """
        result = await db.execute(
            select(UserFundPosition.fund_code)
            .where(UserFundPosition.user_id == user_id, UserFundPosition.del_flag == '0')
            .distinct()
        )
        fund_codes = [row[0] for row in result.all()]
        if not fund_codes:
            return []

        result = await db.execute(
            select(Fund).where(Fund.code.in_(fund_codes), Fund.del_flag == '0')
        )
        funds = list(result.scalars().all())
        if not funds:
            return []

        result = await db.execute(
            select(FundAssetMapping.fund_id).where(
                FundAssetMapping.user_id == user_id,
                FundAssetMapping.fund_id.in_([fund.fund_id for fund in funds]),
            )
        )
        mapped_ids = {row[0] for row in result.all()}
        return [fund for fund in funds if fund.fund_id not in mapped_ids]
