"""角色管理模块 DAO(数据访问层)。

核心约定:所有写操作只 flush 不 commit,事务由 Service 层统一控制。
"""

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.response import PageModel
from module_system.entity.do.role_do import SysRole, SysRoleMenu
from module_system.entity.do.user_do import SysUserRole
from module_system.entity.vo.role_vo import RolePageQueryModel
from utils.page_util import PageUtil


class RoleDao:
    """角色管理模块数据库操作层。"""

    # ==================== 读 ====================

    @classmethod
    async def get_role_by_id(cls, db: AsyncSession, role_id: int) -> SysRole | None:
        """根据 role_id 获取未删除角色。"""
        result = await db.execute(
            select(SysRole).where(SysRole.role_id == role_id, SysRole.del_flag == '0')
        )
        return result.scalars().first()

    @classmethod
    async def get_role_by_name(cls, db: AsyncSession, role_name: str) -> SysRole | None:
        """根据角色名获取未删除角色(唯一性校验用)。"""
        result = await db.execute(
            select(SysRole).where(SysRole.role_name == role_name, SysRole.del_flag == '0')
        )
        return result.scalars().first()

    @classmethod
    async def get_role_by_key(cls, db: AsyncSession, role_key: str) -> SysRole | None:
        """根据权限字符获取未删除角色(唯一性校验用)。"""
        result = await db.execute(
            select(SysRole).where(SysRole.role_key == role_key, SysRole.del_flag == '0')
        )
        return result.scalars().first()

    @classmethod
    async def get_role_list(
        cls, db: AsyncSession, query_object: RolePageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict[str, Any]]:
        """根据查询参数获取角色分页列表。"""
        query = (
            select(SysRole)
            .where(
                SysRole.del_flag == '0',
                # 条件查询:参数非空才追加 where(动态 SQL)
                SysRole.role_name.like(f'%{query_object.role_name}%') if query_object.role_name else True,
                SysRole.role_key.like(f'%{query_object.role_key}%') if query_object.role_key else True,
                SysRole.status == query_object.status if query_object.status else True,
            )
            .order_by(SysRole.role_sort)
        )
        role_list: PageModel | list[dict[str, Any]] = await PageUtil.paginate(
            db, query, query_object.page_num, query_object.page_size, is_page
        )
        return role_list

    @classmethod
    async def get_role_menu_ids(cls, db: AsyncSession, role_id: int) -> list[int]:
        """查角色绑定的全部菜单ID(编辑回显用)。"""
        result = await db.execute(select(SysRoleMenu.menu_id).where(SysRoleMenu.role_id == role_id))
        return [row[0] for row in result.all()]

    @classmethod
    async def count_user_role_by_role_id(cls, db: AsyncSession, role_id: int) -> int:
        """统计角色下的用户数(删除提示用)。"""
        result = await db.execute(
            select(func.count()).select_from(SysUserRole).where(SysUserRole.role_id == role_id)
        )
        return result.scalar() or 0

    # ==================== 写(只 flush,事务由 Service 控制) ====================

    @classmethod
    async def add_role_dao(cls, db: AsyncSession, role: SysRole) -> SysRole:
        """新增角色(flush 回填自增主键)。"""
        db.add(role)
        await db.flush()
        return role

    @classmethod
    async def batch_add_role_menu_dao(cls, db: AsyncSession, role_id: int, menu_ids: list[int]) -> None:
        """批量插入角色-菜单关联。"""
        if menu_ids:
            db.add_all([SysRoleMenu(role_id=role_id, menu_id=mid) for mid in menu_ids])

    @classmethod
    async def edit_role_dao(cls, db: AsyncSession, role: dict) -> None:
        """编辑角色(批量更新语法,dict 含 role_id 作 where 条件)。"""
        await db.execute(update(SysRole), [role])

    @classmethod
    async def delete_role_dao(cls, db: AsyncSession, role_id: int, update_by: str | None, update_time) -> None:
        """逻辑删除角色(只更新 del_flag)。"""
        await db.execute(
            update(SysRole)
            .where(SysRole.role_id == role_id)
            .values(del_flag='2', update_by=update_by, update_time=update_time)
        )

    @classmethod
    async def delete_role_menu_by_role_id(cls, db: AsyncSession, role_id: int) -> None:
        """物理解绑角色-菜单关联。"""
        await db.execute(delete(SysRoleMenu).where(SysRoleMenu.role_id == role_id))

    @classmethod
    async def delete_role_user_by_role_id(cls, db: AsyncSession, role_id: int) -> None:
        """物理解绑用户-角色关联(防幽灵绑定)。"""
        await db.execute(delete(SysUserRole).where(SysUserRole.role_id == role_id))
