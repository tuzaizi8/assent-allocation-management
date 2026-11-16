"""用户管理模块 DAO（数据库访问层）。

核心约定：所有写操作只 flush 不 commit，事务由 Service 层统一控制。
"""

from datetime import datetime, time
from typing import Any

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.response import PageModel
from module_system.entity.do.user_do import SysUser, SysUserRole
from module_system.entity.vo.user_vo import (
    UserModel,
    UserPageQueryModel,
)
from utils.page_util import PageUtil

# 用户查询响应永不携带的敏感列（序列化阶段剔除，列表/详情共用）
_USER_EXCLUDE_COLUMNS = {'password'}


class UserDao:
    """用户管理模块数据库操作层。"""

    @classmethod
    async def get_user_by_id(cls, db: AsyncSession, user_id: int) -> SysUser | None:
        """根据 user_id 获取用户信息。

        注意：只过滤 del_flag——停用用户仍可被查询(详情/编辑/鉴权装配)；
        不过滤 status——停用判断由调用方负责(鉴权路径在 security 层显式拦截，
        对齐 get_user_by_email 的既有模式)。

        :param db: orm 对象
        :param user_id: 用户ID
        :return: 当前 user_id 的用户信息对象
        """
        query_user_info = (
            (
                await db.execute(
                    select(SysUser)
                    .where(SysUser.del_flag == '0', SysUser.user_id == user_id)
                    .order_by(desc(SysUser.create_time))
                    .distinct()
                )
            )
            .scalars()
            .first()
        )
        return query_user_info

    @classmethod
    async def get_user_by_name(cls, db: AsyncSession, user_name: str) -> SysUser | None:
        """根据用户名获取用户信息（用于唯一性校验与登录）。

        :param db: orm 对象
        :param user_name: 用户名
        :return: 当前用户名的用户信息对象
        """
        query_user_info = (
            (
                await db.execute(
                    select(SysUser)
                    .where(SysUser.status == '0', SysUser.del_flag == '0', SysUser.user_name == user_name)
                    .order_by(desc(SysUser.create_time))
                    .distinct()
                )
            )
            .scalars()
            .first()
        )
        return query_user_info

    @classmethod
    async def get_user_by_email(cls, db: AsyncSession, email: str) -> SysUser | None:
        """根据邮箱获取用户信息（登录/注册唯一性校验）。

        注意：不过滤 status——登录时需区分「账号停用」与「账号不存在」，
        停用判断由 Service 层负责。

        :param db: orm 对象
        :param email: 用户邮箱
        :return: 当前邮箱的用户信息对象
        """
        query_user_info = (
            (
                await db.execute(
                    select(SysUser)
                    .where(SysUser.del_flag == '0', SysUser.email == email)
                    .order_by(desc(SysUser.create_time))
                    .distinct()
                )
            )
            .scalars()
            .first()
        )
        return query_user_info

    @classmethod
    async def get_users_by_ids(cls, db: AsyncSession, user_ids: list[int]) -> list[SysUser]:
        """根据 user_id 列表批量获取未删除用户（批量删除前置校验用）。

        注意：只过滤 del_flag——已删除用户不许重复删；不过滤 status——停用用户允许删除。

        :param db: orm 对象
        :param user_ids: 用户ID列表
        :return: 未删除的用户对象列表
        """
        query_list = (
            (await db.execute(select(SysUser).where(SysUser.del_flag == '0', SysUser.user_id.in_(user_ids))))
            .scalars()
            .all()
        )
        return query_list

    @classmethod
    async def get_user_list(
        cls,
        db: AsyncSession,
        query_object: UserPageQueryModel,
        is_page: bool = False,
    ) -> PageModel | list[dict[str, Any]]:
        """根据查询参数获取用户列表信息。

        :param db: orm 对象
        :param query_object: 查询参数对象
        :param is_page: 是否开启分页
        :return: 用户列表信息对象
        """
        query = (
            select(SysUser)
            .where(
                SysUser.del_flag == '0',
                # 条件查询：只有参数非空时才追加 where 条件（动态 SQL）
                SysUser.user_id == query_object.user_id if query_object.user_id is not None else True,
                SysUser.user_name.like(f'%{query_object.user_name}%') if query_object.user_name else True,
                SysUser.nick_name.like(f'%{query_object.nick_name}%') if query_object.nick_name else True,
                SysUser.email.like(f'%{query_object.email}%') if query_object.email else True,
                SysUser.phonenumber.like(f'%{query_object.phonenumber}%') if query_object.phonenumber else True,
                SysUser.status == query_object.status if query_object.status else True,
                SysUser.sex == query_object.sex if query_object.sex else True,
                # 时间范围查询
                SysUser.create_time.between(
                    datetime.combine(datetime.strptime(query_object.begin_time, '%Y-%m-%d'), time(0, 0, 0)),
                    datetime.combine(datetime.strptime(query_object.end_time, '%Y-%m-%d'), time(23, 59, 59)),
                )
                if query_object.begin_time and query_object.end_time
                else True,
            )
            .order_by(SysUser.user_id)
            .distinct()
        )
        user_list: PageModel | list[dict[str, Any]] = await PageUtil.paginate(
            db, query, query_object.page_num, query_object.page_size, is_page,
            exclude=_USER_EXCLUDE_COLUMNS,
        )
        return user_list

    @classmethod
    async def get_user_role_ids(cls, db: AsyncSession, user_id: int) -> list[int]:
        """查用户绑定的全部角色ID(编辑回显勾选用)。

        :param db: orm 对象
        :param user_id: 用户ID
        :return: 用户绑定的角色ID列表
        """
        result = await db.execute(select(SysUserRole.role_id).where(SysUserRole.user_id == user_id))
        return [row[0] for row in result.all()]

    @classmethod
    async def batch_add_user_role_dao(cls, db: AsyncSession, user_id: int, role_ids: list[int]) -> None:
        """批量插入用户-角色关联(只 add 不 flush，事务由 Service 层控制)。

        :param db: orm 对象
        :param user_id: 用户ID
        :param role_ids: 角色ID列表
        """
        if role_ids:
            db.add_all([SysUserRole(user_id=user_id, role_id=rid) for rid in role_ids])

    @classmethod
    async def add_user_dao(cls, db: AsyncSession, user: UserModel) -> SysUser:
        """新增用户数据库操作。

        :param db: orm 对象
        :param user: 用户对象
        :return: 新增后的用户对象（含自增主键 user_id）
        """
        db_user = SysUser(**user.model_dump(exclude={'admin'}))
        db.add(db_user)
        # 关键：只 flush 不 commit，把 INSERT 发送到数据库拿到主键，但事务由 Service 层提交
        await db.flush()
        return db_user

    @classmethod
    async def edit_user_dao(cls, db: AsyncSession, user: dict) -> None:
        """编辑用户数据库操作。

        :param db: orm 对象
        :param user: 需要更新的用户字典（含 user_id 作为 where 条件）
        """
        # 批量更新语法：update(SysUser) 接收字典列表，自动用主键匹配
        await db.execute(update(SysUser), [user])

    @classmethod
    async def delete_user_dao(cls, db: AsyncSession, user_ids: list[int], update_by: str | None, update_time: datetime | None) -> None:
        """批量删除用户数据库操作（逻辑删除）。

        :param db: orm 对象
        :param user_ids: 用户ID列表（WHERE IN 单条 SQL 批量生效）
        :param update_by: 更新者（审计字段，取自请求上下文）
        :param update_time: 更新时间（审计字段）
        """
        # 逻辑删除：只更新 del_flag，不物理删除；IN 一条 SQL 替代逐条 UPDATE
        await db.execute(
            update(SysUser)
            .where(SysUser.user_id.in_(user_ids))
            .values(del_flag='2', update_by=update_by, update_time=update_time)
        )

    @classmethod
    async def delete_user_role_by_user_ids(cls, db: AsyncSession, user_ids: list[int]) -> None:
        """物理删除用户-角色关联（用户已逻辑删除，残留关联是幽灵数据，一并清理）。

        :param db: orm 对象
        :param user_ids: 用户ID列表
        """
        await db.execute(delete(SysUserRole).where(SysUserRole.user_id.in_(user_ids)))