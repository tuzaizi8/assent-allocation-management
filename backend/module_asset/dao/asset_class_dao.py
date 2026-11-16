"""资产配置模块 DAO(数据访问层):资产类别。

核心约定:所有写操作只 flush 不 commit,事务由 Service 层统一控制。
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from module_asset.entity.do.asset_class_do import AssetClass


class AssetClassDao:
    """资产类别数据库操作层。"""

    @classmethod
    async def get_asset_classes(cls, db: AsyncSession, user_id: int) -> list[AssetClass]:
        """获取用户全部资产类别(按排序顺序)。"""
        result = await db.execute(
            select(AssetClass)
            .where(AssetClass.user_id == user_id)
            .order_by(AssetClass.sort_order, AssetClass.asset_class_id)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_asset_class_by_id(
        cls, db: AsyncSession, asset_class_id: int, user_id: int
    ) -> AssetClass | None:
        """获取单个资产类别(行级归属校验)。"""
        result = await db.execute(
            select(AssetClass).where(
                AssetClass.asset_class_id == asset_class_id,
                AssetClass.user_id == user_id,
            )
        )
        return result.scalars().first()

    @classmethod
    async def add_asset_class_dao(cls, db: AsyncSession, asset_class: AssetClass) -> AssetClass:
        """新增资产类别(flush 回填自增主键)。"""
        db.add(asset_class)
        await db.flush()
        return asset_class

    @classmethod
    async def delete_asset_class_dao(cls, db: AsyncSession, asset_class_id: int) -> None:
        """物理删除资产类别(引用检查由 Service 前置完成)。"""
        await db.execute(delete(AssetClass).where(AssetClass.asset_class_id == asset_class_id))
