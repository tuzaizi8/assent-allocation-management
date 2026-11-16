"""资产配置模块 DAO(数据访问层):配置模式。

核心约定:所有写操作只 flush 不 commit,事务由 Service 层统一控制。
"""

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_asset.entity.do.asset_class_do import AssetClassMode


class AssetClassModeDao:
    """配置模式数据库操作层。"""

    @classmethod
    async def get_modes(cls, db: AsyncSession, user_id: int) -> list[AssetClassMode]:
        """获取用户全部配置模式。"""
        result = await db.execute(
            select(AssetClassMode).where(AssetClassMode.user_id == user_id).order_by(AssetClassMode.mode_id)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_mode_by_id(cls, db: AsyncSession, mode_id: int, user_id: int) -> AssetClassMode | None:
        """获取单个配置模式(行级归属校验)。"""
        result = await db.execute(
            select(AssetClassMode).where(
                AssetClassMode.mode_id == mode_id,
                AssetClassMode.user_id == user_id,
            )
        )
        return result.scalars().first()

    @classmethod
    async def add_mode_dao(cls, db: AsyncSession, mode: AssetClassMode) -> AssetClassMode:
        """新增配置模式(flush 回填自增主键)。"""
        db.add(mode)
        await db.flush()
        return mode

    @classmethod
    async def delete_mode_dao(cls, db: AsyncSession, mode_id: int) -> None:
        """物理删除配置模式(关联目标占比清理由 Service 编排)。"""
        await db.execute(delete(AssetClassMode).where(AssetClassMode.mode_id == mode_id))

    @classmethod
    async def clear_default_for_user(cls, db: AsyncSession, user_id: int) -> None:
        """清除用户全部模式的默认标记(set-default 互斥的前半步)。"""
        await db.execute(
            update(AssetClassMode)
            .where(AssetClassMode.user_id == user_id, AssetClassMode.is_default == True)  # noqa: E712
            .values(is_default=False)
        )
