"""用户管理模块 Service（业务逻辑层）。

核心职责：业务校验 + 事务控制（commit/rollback）。
所有写操作的 commit/rollback 都在本层完成，DAO 层只 flush。
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.constants import CommonConstant
from common.response import CrudResponseModel, PageModel
from core.context_utils import get_current_user_or_none
from exceptions.exceptions import ServiceException,ServiceWarning
from module_system.dao.user_dao import UserDao
from module_system.entity.vo.user_vo import (
    DeleteUserModel,
    UserAddModel,
    UserEditModel,
    UserModel,
    UserPageQueryModel,
)
from utils.camel_case_util import CamelCaseUtil
from utils.log import logger


class UserService:
    """用户管理模块服务层。"""

    @classmethod
    async def get_user_list_services(
        cls,
        query_db: AsyncSession,
        query_object: UserPageQueryModel,
        is_page: bool = False,
    ) -> PageModel | list[dict[str, Any]]:
        """获取用户列表信息 service。

        :param query_db: orm 对象
        :param query_object: 查询参数对象
        :param is_page: 是否开启分页
        :return: 用户列表信息对象
        """
        # 查询操作无需事务控制，直接调用 DAO
        query_result = await UserDao.get_user_list(query_db, query_object, is_page)
        return query_result

    @classmethod
    async def user_detail_services(cls, query_db: AsyncSession, user_id: int) -> dict[str, Any]:
        """获取用户详细信息 service（含 roleIds，编辑弹窗勾选回显用）。

        对齐 role 模块 get_role_detail_services 的 dict 模式（RoleDetail.menuIds 同构）。

        :param query_db: orm 对象
        :param user_id: 用户id
        :return: 驼峰 dict（含 roleIds，不含 password）
        """
        user = await UserDao.get_user_by_id(query_db, user_id)
        if not user:
            raise ServiceException(message='用户不存在')
        # DO -> 驼峰 dict（exclude 剔除密码，与列表路径共用同一裁剪机制）
        user_dict = CamelCaseUtil.transform_result(user, exclude={'password'})
        user_dict['roleIds'] = await UserDao.get_user_role_ids(query_db, user_id)
        return user_dict

    @classmethod
    async def check_user_name_unique_services(cls, query_db: AsyncSession, page_object: UserModel) -> bool:
        """校验用户名是否唯一 service。

        :param query_db: orm 对象
        :param page_object: 用户对象
        :return: 校验结果（True 唯一 / False 已存在）
        """
        # 新增时 user_id 为 None，用 -1 占位，确保不会匹配到自身
        user_id = -1 if page_object.user_id is None else page_object.user_id
        user = await UserDao.get_user_by_name(query_db, page_object.user_name)
        if user and user.user_id != user_id:
            return CommonConstant.NOT_UNIQUE
        return CommonConstant.UNIQUE

    @classmethod
    async def add_user_services(cls, query_db: AsyncSession, page_object: UserAddModel) -> CrudResponseModel:
        """新增用户信息 service。

        :param query_db: orm 对象
        :param page_object: 新增用户对象
        :return: 新增用户校验结果
        """
        # exclude 显式剔除关联字段(role_ids/post_ids 不是 sys_user 列)
        add_user = UserModel(**page_object.model_dump(by_alias=True, exclude={'role_ids', 'post_ids'}))
        # 业务校验：用户名唯一
        if not await cls.check_user_name_unique_services(query_db, page_object):
            raise ServiceWarning(message=f'新增用户{page_object.user_name}失败，登录账号已存在')
        # 全局单选约束(需求修订 2026-08-27):一个用户至多绑定一个角色
        # (前端 RadioGroup 单选,后端防御兜底——前后端双保障)
        if page_object.role_ids and len(page_object.role_ids) > 1:
            raise ServiceWarning(message='一个用户只能绑定一个角色')
        try:
            # 调用 DAO 层执行 INSERT（只 flush 不 commit）
            add_result = await UserDao.add_user_dao(query_db, add_user)
            user_id, user_name = add_result.user_id, add_user.user_name  # ← commit 前取值(属性会过期)
            # 绑定角色(对齐 role 模块 batch_add_role_menu_dao 范式，只 add 不 flush)
            if page_object.role_ids:
                await UserDao.batch_add_user_role_dao(query_db, user_id, page_object.role_ids)
            # 所有 DAO 操作成功后，统一提交事务
            await query_db.commit()
            logger.info(
                f"[用户] 新增成功 user_name={user_name} user_id={user_id} "
                f"绑定角色数={len(page_object.role_ids or [])}"
            )
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            # 任何一步失败，回滚所有 flush 的改动
            await query_db.rollback()
            logger.error(f"[用户] 新增失败回滚 user_name={add_user.user_name} | {e}")
            raise e

    @classmethod
    async def edit_user_services(cls, query_db: AsyncSession, page_object: UserEditModel) -> CrudResponseModel:
        """编辑用户信息 service。

        :param query_db: orm 对象
        :param page_object: 编辑用户对象
        :return: 编辑用户校验结果
        """
        # exclude_unset=True：只序列化前端实际传入的字段，避免把未传字段更新成 None
        edit_user = page_object.model_dump(exclude_unset=True, exclude={'admin'})
        # 角色关联不进用户表更新（pop 防止 update(SysUser) 收到未知列报错）
        role_ids = edit_user.pop('role_ids', None)
        edit_user.pop('role', None)
        # 空密码防御:前端「留空=不修改」传空串时剔除,避免密码被更新成空串
        if edit_user.get('password') == '':
            edit_user.pop('password', None)
        # 注意:user_detail_services 返回驼峰 dict,取值用 'userId'(edit_user 本身是 snake_case)
        user_info = await cls.user_detail_services(query_db, edit_user.get('user_id'))
        if user_info and user_info.get('userId'):
            # 超管保护:user_id=1 不允许停用(B1 接线后停用即 401,超管被锁死无解)
            if user_info.get('userId') == 1 and page_object.status == '1':
                raise ServiceWarning(message='超级管理员不允许停用')
            # 超管保护:admin 通配来自持有 admin 角色(sys_user_role 装配)，
            # user_id=1 失去它 = 界面锁死无解(同停用保护级别)
            if user_info.get('userId') == 1 and role_ids is not None and 1 not in role_ids:
                raise ServiceWarning(message='超级管理员必须保留管理员角色')
            # 全局单选约束(需求修订 2026-08-27):一个用户至多绑定一个角色
            # (前端 RadioGroup 单选,后端防御兜底——前后端双保障)
            if page_object.role_ids and len(page_object.role_ids) > 1:
                raise ServiceWarning(message='一个用户只能绑定一个角色')
            # 业务校验：用户名唯一（排除自身）
            if not await cls.check_user_name_unique_services(query_db, page_object):
                raise ServiceWarning(message=f'修改用户{page_object.user_name}失败，登录账号已存在')
            try:
                await UserDao.edit_user_dao(query_db, edit_user)
                # 角色绑定全量替换语义(对齐 edit_role_services 的 menu_ids):
                # 前端提交勾选全集，后端先删后插——提交什么，绑定就是什么
                if role_ids is not None:
                    await UserDao.delete_user_role_by_user_ids(query_db, [edit_user.get('user_id')])
                    await UserDao.batch_add_user_role_dao(query_db, edit_user.get('user_id'), role_ids)
                await query_db.commit()
                logger.info(
                    f"[用户] 编辑成功 user_id={edit_user.get('user_id')} "
                    f"绑定角色数={len(role_ids) if role_ids is not None else '未变更'}"
                )
                return CrudResponseModel(is_success=True, message='更新成功')
            except Exception as e:
                await query_db.rollback()
                logger.error(f"[用户] 编辑失败回滚 user_id={edit_user.get('user_id')} | {e}")
                raise e
        else:
            raise ServiceException(message='用户不存在')

    @classmethod
    async def delete_user_services(cls, query_db: AsyncSession, page_object: DeleteUserModel) -> CrudResponseModel:
        """删除用户信息 service（逻辑删除 + 关联解绑，支持批量）。

        校验链:格式 → 超管保护 → 自删保护 → 存在性,全部通过才动库。

        :param query_db: orm 对象
        :param page_object: 删除用户对象
        :return: 删除用户校验结果
        """
        if not page_object.user_ids:
            raise ServiceWarning(message='传入用户ID为空')
        # ① 拆分 + 去空白 + 去重(保持原顺序),格式非法返回 601 而非 500
        raw_ids = [raw.strip() for raw in page_object.user_ids.split(',') if raw.strip()]
        try:
            user_id_list = list(dict.fromkeys(int(raw) for raw in raw_ids))
        except ValueError as e:
            raise ServiceWarning(message='用户ID格式不正确(应为逗号分隔的数字)') from e
        if not user_id_list:
            raise ServiceWarning(message='传入用户ID为空')
        # ② 超级管理员保护(UserModel.check_admin 同款锚点:user_id == 1)
        if 1 in user_id_list:
            raise ServiceWarning(message='超级管理员不允许删除')
        # ③ 当前登录用户不能删除自己(B1 接线后从请求上下文取)
        current_user = get_current_user_or_none()
        if current_user and current_user.user_id in user_id_list:
            raise ServiceWarning(message='当前用户不能删除自己')
        # ④ 存在性前置校验:全部通过才动库(避免半删状态)
        existing_users = await UserDao.get_users_by_ids(query_db, user_id_list)
        existing_ids = {user.user_id for user in existing_users}
        missing_ids = [str(uid) for uid in user_id_list if uid not in existing_ids]
        if missing_ids:
            raise ServiceWarning(message=f'用户不存在或已删除(user_id={",".join(missing_ids)})')
        try:
            # ⑤ 批量逻辑删除(IN 单条 SQL)+ 解绑用户-角色关联(幽灵数据清理)
            await UserDao.delete_user_dao(
                query_db, user_id_list, page_object.update_by, page_object.update_time
            )
            await UserDao.delete_user_role_by_user_ids(query_db, user_id_list)
            await query_db.commit()
            logger.info(f'[用户] 删除成功 user_ids={page_object.user_ids}(已解绑角色关联)')
            return CrudResponseModel(is_success=True, message='删除成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f"[用户] 删除失败回滚 user_ids={page_object.user_ids} | {e}")
            raise e