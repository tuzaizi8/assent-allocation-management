"""角色管理模块 Service(业务逻辑层)。

职责:业务校验(唯一性/内置角色保护)+ 角色与菜单绑定的全量替换 + 事务控制。
契约见知识库《02-角色管理页》。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from common.response import CrudResponseModel, PageModel
from exceptions.exceptions import ServiceWarning
from module_system.dao.role_dao import RoleDao
from module_system.entity.do.role_do import SysRole
from module_system.entity.vo.role_vo import (
    DeleteRoleModel,
    RoleAddModel,
    RoleEditModel,
    RolePageQueryModel,
)
from utils.camel_case_util import CamelCaseUtil
from utils.log import logger


class RoleService:
    """角色管理模块服务层。"""

    # ---------- 查询 ----------

    @classmethod
    async def get_role_list_services(
        cls, query_db: AsyncSession, query_object: RolePageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict]:
        """获取角色分页列表。"""
        return await RoleDao.get_role_list(query_db, query_object, is_page)

    @classmethod
    async def get_role_detail_services(cls, query_db: AsyncSession, role_id: int) -> dict:
        """获取角色详情(含 menuIds,编辑回显勾选用)。"""
        role = await RoleDao.get_role_by_id(query_db, role_id)
        if role is None:
            raise ServiceWarning(message='角色不存在')
        role_dict = CamelCaseUtil.transform_result(role)
        role_dict['menuIds'] = await RoleDao.get_role_menu_ids(query_db, role_id)
        return role_dict

    # ---------- 校验 ----------

    @classmethod
    async def _check_role_unique(
        cls,
        query_db: AsyncSession,
        role_name: str | None,
        role_key: str | None,
        exclude_id: int = -1,
    ) -> None:
        """角色名/权限字符唯一性校验(编辑时排除自身;已删角色不占名)。

        :raises ServiceWarning: 冲突(→ code 601)
        """
        if role_name:
            by_name = await RoleDao.get_role_by_name(query_db, role_name)
            if by_name and by_name.role_id != exclude_id:
                raise ServiceWarning(message=f'角色名称「{role_name}」已存在')
        if role_key:
            by_key = await RoleDao.get_role_by_key(query_db, role_key)
            if by_key and by_key.role_id != exclude_id:
                raise ServiceWarning(message=f'角色权限字符「{role_key}」已存在')

    # ---------- 写操作 ----------

    @classmethod
    async def add_role_services(cls, query_db: AsyncSession, page_object: RoleAddModel) -> CrudResponseModel:
        """新增角色:唯一性校验 → 落库 → 绑定菜单。"""
        await cls._check_role_unique(query_db, page_object.role_name, page_object.role_key)
        try:
            add_role = SysRole(**page_object.model_dump(exclude={'role_id', 'menu_ids', 'admin'}))
            add_result = await RoleDao.add_role_dao(query_db, add_role)
            role_id, role_name = add_result.role_id, add_role.role_name  # commit 前取值(属性会过期)
            await RoleDao.batch_add_role_menu_dao(query_db, role_id, page_object.menu_ids or [])
            await query_db.commit()
            logger.info(
                f'[角色] 新增成功 role_name={role_name} role_id={role_id} '
                f'绑定菜单数={len(page_object.menu_ids or [])}'
            )
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[角色] 新增失败回滚 role_name={page_object.role_name} | {e}')
            raise e

    @classmethod
    async def edit_role_services(cls, query_db: AsyncSession, page_object: RoleEditModel) -> CrudResponseModel:
        """编辑角色:唯一性校验 + 内置角色保护 + 菜单绑定全量替换。

        内置保护:admin(role_id=1)是权限体系通配锚点(interface_auth 按 role_key='admin' 通配),
        其权限字符禁止修改——改了会让全部超管瞬间失去通配。
        """
        role_id = page_object.role_id
        if role_id is None:
            raise ServiceWarning(message='修改角色失败，缺少角色ID')
        role = await RoleDao.get_role_by_id(query_db, role_id)
        if role is None:
            raise ServiceWarning(message=f'修改角色{page_object.role_name}失败，角色不存在')
        if role_id == 1 and page_object.role_key and page_object.role_key != role.role_key:
            raise ServiceWarning(message='内置管理员角色的权限字符不允许修改')
        await cls._check_role_unique(query_db, page_object.role_name, page_object.role_key, role_id)
        try:
            edit_role = page_object.model_dump(exclude_unset=True, exclude={'menu_ids', 'admin'})
            await RoleDao.edit_role_dao(query_db, edit_role)
            # 菜单绑定全量替换语义:前端提交勾选全集,后端先删后插
            menu_ids = page_object.menu_ids
            if menu_ids is not None:
                await RoleDao.delete_role_menu_by_role_id(query_db, role_id)
                await RoleDao.batch_add_role_menu_dao(query_db, role_id, menu_ids)
            await query_db.commit()
            logger.info(f'[角色] 编辑成功 role_id={role_id} 绑定菜单数={len(menu_ids or []) if menu_ids is not None else "未变更"}')
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[角色] 编辑失败回滚 role_id={role_id} | {e}')
            raise e

    @classmethod
    async def delete_role_services(cls, query_db: AsyncSession, page_object: DeleteRoleModel) -> CrudResponseModel:
        """删除角色(逻辑删除):内置角色保护 + 关联解绑。

        解绑范围:sys_role_menu(角色-菜单)+ sys_user_role(用户-角色)——
        角色已逻辑删除,残留关联是幽灵数据,一并物理清理。
        """
        if not page_object.role_ids:
            raise ServiceWarning(message='传入角色ID为空')
        role_id_list = page_object.role_ids.split(',')
        # 前置校验全部通过才动库(避免半删状态)
        if '1' in role_id_list:
            raise ServiceWarning(message='内置管理员角色不允许删除')
        for role_id in role_id_list:
            role = await RoleDao.get_role_by_id(query_db, int(role_id))
            if role is None:
                raise ServiceWarning(message=f'角色不存在(role_id={role_id})')
        try:
            for role_id in role_id_list:
                rid = int(role_id)
                user_count = await RoleDao.count_user_role_by_role_id(query_db, rid)
                await RoleDao.delete_role_dao(query_db, rid, page_object.update_by, page_object.update_time)
                await RoleDao.delete_role_menu_by_role_id(query_db, rid)
                await RoleDao.delete_role_user_by_role_id(query_db, rid)
                logger.info(f'[角色] 删除 role_id={rid}(解绑用户数={user_count})')
            await query_db.commit()
            logger.info(f'[角色] 删除成功 role_ids={page_object.role_ids}')
            return CrudResponseModel(is_success=True, message='删除成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[角色] 删除失败回滚 role_ids={page_object.role_ids} | {e}')
            raise e
