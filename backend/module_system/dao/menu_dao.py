"""菜单模块 DAO(数据访问层)。"""

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_system.entity.do.menu_do import SysMenu
from module_system.entity.do.role_do import SysRole, SysRoleMenu
from module_system.entity.do.user_do import SysUserRole


class MenuDao:
    """菜单模块数据访问层。"""

    @classmethod
    async def get_user_role_keys(cls, db: AsyncSession, user_id: int) -> list[str]:
        """查用户的所有 role_key(过滤停用/删除角色)。admin 判定与 role 装配共用。"""
        result = await db.execute(
            select(SysRole.role_key)
            .join(SysUserRole, SysUserRole.role_id == SysRole.role_id)
            .where(
                SysUserRole.user_id == user_id,
                SysRole.status == '0',
                SysRole.del_flag == '0',
            )
        )
        return [row[0] for row in result.all()]

    @classmethod
    async def get_all_menus(cls, db: AsyncSession) -> list[SysMenu]:
        """查全部启用菜单(admin 全量场景,含 F 按钮——perms 装配需要)。"""
        result = await db.execute(
            select(SysMenu).where(SysMenu.status == '0').order_by(SysMenu.order_num)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_visible_menus_by_user_id(cls, db: AsyncSession, user_id: int) -> list[SysMenu]:
        """查用户角色关联的启用菜单(普通用户场景,含 F 按钮)。

        链路:sys_user_role → sys_role(过滤) → sys_role_menu → sys_menu(过滤)。
        """
        result = await db.execute(
            select(SysMenu)
            .join(SysRoleMenu, SysRoleMenu.menu_id == SysMenu.menu_id)
            .join(SysRole, SysRole.role_id == SysRoleMenu.role_id)
            .join(SysUserRole, SysUserRole.role_id == SysRole.role_id)
            .where(
                SysUserRole.user_id == user_id,
                SysRole.status == '0',
                SysRole.del_flag == '0',
                SysMenu.status == '0',
            )
            .distinct()
            .order_by(SysMenu.order_num)
        )
        return list(result.scalars().all())

    # ==================== 菜单管理页 CRUD(2026-08-23) ====================

    @classmethod
    async def get_menu_by_id(cls, db: AsyncSession, menu_id: int) -> SysMenu | None:
        """根据 menu_id 获取菜单(管理页编辑/父菜单校验用;不过滤状态——管理端看全貌)。"""
        result = await db.execute(select(SysMenu).where(SysMenu.menu_id == menu_id))
        return result.scalars().first()

    @classmethod
    async def get_menu_list(cls, db: AsyncSession, menu_name: str | None = None) -> list[SysMenu]:
        """获取菜单全量列表(含 F 按钮与隐藏项,管理页树形展示用,不分页)。

        :param db: orm 对象
        :param menu_name: 菜单名称模糊过滤(空=全量)
        """
        query = (
            select(SysMenu)
            .where(SysMenu.menu_name.like(f'%{menu_name}%') if menu_name else True)
            .order_by(SysMenu.parent_id, SysMenu.order_num)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def add_menu_dao(cls, db: AsyncSession, menu: SysMenu) -> SysMenu:
        """新增菜单(只 flush 不 commit,事务由 Service 层统一控制)。"""
        db.add(menu)
        await db.flush()  # 回填自增 menu_id
        return menu

    @classmethod
    async def edit_menu_dao(cls, db: AsyncSession, menu: dict) -> None:
        """编辑菜单(批量更新语法,dict 含 menu_id 作 where 条件)。"""
        await db.execute(update(SysMenu), [menu])

    @classmethod
    async def delete_menu_dao(cls, db: AsyncSession, menu_id: int) -> None:
        """物理删除菜单(sys_menu 无 del_flag 字段,与若依一致)。"""
        await db.execute(delete(SysMenu).where(SysMenu.menu_id == menu_id))

    @classmethod
    async def count_child_by_parent_id(cls, db: AsyncSession, parent_id: int) -> int:
        """统计菜单的直接子菜单数(删除保护:存在子菜单禁删)。"""
        result = await db.execute(
            select(func.count()).select_from(SysMenu).where(SysMenu.parent_id == parent_id)
        )
        return result.scalar() or 0

    @classmethod
    async def count_role_menu_by_menu_id(cls, db: AsyncSession, menu_id: int) -> int:
        """统计菜单被多少角色引用(删除保护:被角色引用禁删)。"""
        result = await db.execute(
            select(func.count()).select_from(SysRoleMenu).where(SysRoleMenu.menu_id == menu_id)
        )
        return result.scalar() or 0
    @classmethod
    async def get_perms_by_user_id(cls, db: AsyncSession, user_id: int) -> list[SysMenu]:
        """查用户全部权限标识(含 F 按钮——按钮权限也在 sys_menu,与若依一致)。"""
        menus = await cls.get_visible_menus_by_user_id(db, user_id)
        return list({m.perms for m in menus if m.perms})