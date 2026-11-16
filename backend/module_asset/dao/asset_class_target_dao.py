"""资产配置模块 DAO(数据访问层):目标占比。

核心约定:所有写操作只 flush 不 commit,事务由 Service 层统一控制。
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from module_asset.entity.do.asset_class_do import AssetClassTarget


class AssetClassTargetDao:
    """目标占比数据库操作层。"""

    @classmethod
    async def get_targets_by_mode(cls, db: AsyncSession, mode_id: int) -> list[AssetClassTarget]:
        """获取模式下的全部目标占比。"""
        result = await db.execute(
            select(AssetClassTarget).where(AssetClassTarget.mode_id == mode_id)
        )
        return list(result.scalars().all())

    @classmethod
    async def add_target_dao(cls, db: AsyncSession, target: AssetClassTarget) -> AssetClassTarget:
        """新增目标占比(flush 回填自增主键)。"""
        db.add(target)
        await db.flush()
        return target

    @classmethod
    async def delete_targets_by_mode(cls, db: AsyncSession, mode_id: int) -> None:
        """删除模式下的全部目标占比(全量替换的前半步)。"""
        await db.execute(delete(AssetClassTarget).where(AssetClassTarget.mode_id == mode_id))

    @classmethod
    async def delete_targets_by_asset_class(cls, db: AsyncSession, asset_class_id: int) -> None:
        """删除资产类别在全部模式下的目标占比(类别删除的级联清理)。"""
        await db.execute(delete(AssetClassTarget).where(AssetClassTarget.asset_class_id == asset_class_id))
