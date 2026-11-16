"""菜单模块 Service(业务逻辑层)。

getRouters 契约见知识库《04-权限与菜单对接》5.1:
只返回 menuType in (M, C) 且 visible→boolean,字段 camelCase 对齐前端 MenuItem。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from common.constants import ADMIN_ROLE_KEY
from common.response import CrudResponseModel
from exceptions.exceptions import ServiceWarning
from module_system.dao.menu_dao import MenuDao
from module_system.entity.do.menu_do import SysMenu
from module_system.entity.vo.menu_vo import MenuAddModel, MenuEditModel
from utils.camel_case_util import CamelCaseUtil
from utils.log import logger


class MenuService:
    """菜单模块服务层。"""

    @classmethod
    async def get_routers_services(cls, db: AsyncSession, user_id: int) -> list[dict]:
        """组装当前用户的动态菜单树。

        链路:查角色 → admin 特判全量 → 过滤 M/C → dict 索引组树。
        F 按钮不进菜单树(它只贡献 perms,装配在 AuthService.build_auth_user 侧)。
        """
        role_keys = await MenuDao.get_user_role_keys(db, user_id)
        if ADMIN_ROLE_KEY in role_keys:
            menus = await MenuDao.get_all_menus(db)
        else:
            menus = await MenuDao.get_visible_menus_by_user_id(db, user_id)

        mc_menus = [m for m in menus if m.menu_type in ('M', 'C')]
        logger.debug(f'[菜单] getRouters 组装完成 user_id={user_id} 角色={role_keys} 菜单数={len(mc_menus)}')
        return cls._build_tree(mc_menus)

    @classmethod
    def _build_tree(cls, menus: list[SysMenu]) -> list[dict]:
        """SysMenu 列表 → MenuItem dict 标(dict 索引一次遍历,不递归查库)。"""
        menu_map: dict[int, dict] = {}
        for m in menus:
            menu_map[m.menu_id] = {
                'id': m.menu_id,
                'parentId': m.parent_id or 0,
                'name': m.menu_name,
                'path': m.path or '',
                'component': m.component or '',
                'perms': m.perms or '',
                'menuType': m.menu_type,
                'visible': m.visible == '0',  # DB '0'/'1' char → boolean(契约要求)
                'icon': m.icon or '#',
            }
        tree: list[dict] = []
        for m in menus:
            node = menu_map[m.menu_id]
            parent = menu_map.get(m.parent_id or 0)
            if parent is None:
                tree.append(node)  # 根节点(父不在结果集时也挂顶层,容错)
            else:
                parent.setdefault('children', []).append(node)
        # menus 已按 order_num 排序,children 顺序随之正确
        return tree

    # ==================== 菜单管理页 CRUD(2026-08-23) ====================

    @classmethod
    async def get_menu_list_services(cls, db: AsyncSession, menu_name: str | None = None) -> list[dict]:
        """菜单全量列表(含 F 按钮与隐藏项,前端组树拍平展示;不分页——菜单量小且树形)。"""
        menus = await MenuDao.get_menu_list(db, menu_name)
        return [CamelCaseUtil.transform_result(m) for m in menus]

    @classmethod
    async def add_menu_services(cls, db: AsyncSession, page_object: MenuAddModel) -> CrudResponseModel:
        """新增菜单:父菜单存在性 + F 按钮 perms 必填校验。

        :raises ServiceWarning: 校验不通过(→ code 601)
        """
        # 父菜单校验(0/None=根目录,跳过)
        if page_object.parent_id:
            parent = await MenuDao.get_menu_by_id(db, page_object.parent_id)
            if parent is None:
                raise ServiceWarning(message=f'新增菜单{page_object.menu_name}失败，父菜单不存在')
        # F 按钮必须有 perms(无 perms 的按钮是死数据,前端 HasPermission 永远不中)
        if page_object.menu_type == 'F' and not page_object.perms:
            raise ServiceWarning(message=f'新增菜单{page_object.menu_name}失败，按钮类型必须填写权限标识')
        try:
            add_menu = SysMenu(**page_object.model_dump(exclude={'menu_id'}))
            add_result = await MenuDao.add_menu_dao(db, add_menu)
            menu_id, menu_name = add_result.menu_id, add_menu.menu_name  # commit 前取值(属性会过期)
            await db.commit()
            logger.info(f'[菜单] 新增成功 menu_name={menu_name} menu_id={menu_id}')
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await db.rollback()
            logger.error(f'[菜单] 新增失败回滚 menu_name={page_object.menu_name} | {e}')
            raise e

    @classmethod
    async def edit_menu_services(cls, db: AsyncSession, page_object: MenuEditModel) -> CrudResponseModel:
        """编辑菜单:父菜单防环校验(父≠自己、父∉自己的子孙)。"""
        menu_id = page_object.menu_id
        if menu_id is None:
            raise ServiceWarning(message='修改菜单失败，缺少菜单ID')
        menu = await MenuDao.get_menu_by_id(db, menu_id)
        if menu is None:
            raise ServiceWarning(message=f'修改菜单{page_object.menu_name}失败，菜单不存在')
        if page_object.parent_id:
            if page_object.parent_id == menu_id:
                raise ServiceWarning(message=f'修改菜单{page_object.menu_name}失败，上级菜单不能选择自己')
            all_menus = await MenuDao.get_menu_list(db)
            if page_object.parent_id in cls._collect_descendant_ids(all_menus, menu_id):
                raise ServiceWarning(message=f'修改菜单{page_object.menu_name}失败，上级菜单不能选择自己的子菜单')
        if page_object.menu_type == 'F' and not page_object.perms:
            raise ServiceWarning(message=f'修改菜单{page_object.menu_name}失败，按钮类型必须填写权限标识')
        try:
            # exclude_unset:只更新前端实际传入字段,避免未传字段被刷成 None
            edit_menu = page_object.model_dump(exclude_unset=True)
            await MenuDao.edit_menu_dao(db, edit_menu)
            await db.commit()
            logger.info(f'[菜单] 编辑成功 menu_id={menu_id}')
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await db.rollback()
            logger.error(f'[菜单] 编辑失败回滚 menu_id={menu_id} | {e}')
            raise e

    @classmethod
    async def delete_menu_services(cls, db: AsyncSession, menu_id: int) -> CrudResponseModel:
        """删除菜单(物理删除,sys_menu 无 del_flag):子菜单/角色引用双重保护。"""
        child_count = await MenuDao.count_child_by_parent_id(db, menu_id)
        if child_count > 0:
            raise ServiceWarning(message=f'删除菜单失败，存在{child_count}个子菜单，不允许删除')
        role_count = await MenuDao.count_role_menu_by_menu_id(db, menu_id)
        if role_count > 0:
            raise ServiceWarning(message=f'删除菜单失败，菜单已分配给{role_count}个角色，请先取消分配')
        try:
            await MenuDao.delete_menu_dao(db, menu_id)
            await db.commit()
            logger.info(f'[菜单] 删除成功 menu_id={menu_id}')
            return CrudResponseModel(is_success=True, message='删除成功')
        except Exception as e:
            await db.rollback()
            logger.error(f'[菜单] 删除失败回滚 menu_id={menu_id} | {e}')
            raise e

    @classmethod
    def _collect_descendant_ids(cls, menus: list[SysMenu], root_id: int) -> set[int]:
        """收集菜单全部后代 id(迭代法;visited 集合防脏数据环引用死循环)。"""
        children_map: dict[int, list[int]] = {}
        for m in menus:
            children_map.setdefault(m.parent_id or 0, []).append(m.menu_id)
        result: set[int] = set()
        stack = list(children_map.get(root_id, []))
        while stack:
            mid = stack.pop()
            if mid in result:
                continue
            result.add(mid)
            stack.extend(children_map.get(mid, []))
        return result