"""接口级权限校验依赖。

用法:
    @router.get('/list')
    async def list_users(
        _: None = CheckUserInterfaceAuth('system:user:list'),  # 挂依赖
        ...
    ):

语义:
    - 依赖内实时查库装配当前用户 permissions(不缓存——权限收回即时生效)
    - admin 角色通配放行(等价 '*:*:*')
    - 无权限 → PermissionException → 全局处理器 → code 403
    - is_strict(全部/任一)多 perms 版本留作扩展,当前单 perm 校验
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from common.constants import ADMIN_ROLE_KEY
from core.security import get_current_user
from db.get_db import get_db
from exceptions.exceptions import PermissionException
from module_system.dao.menu_dao import MenuDao
from utils.log import logger


def CheckUserInterfaceAuth(perm: str):  # noqa: N802(沿用若依命名惯例)
    """接口权限校验依赖工厂:校验当前用户是否拥有指定 perms。"""
    async def _check_interface_perm(
        current_user: Annotated[dict, Depends(get_current_user)],
        query_db: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        user_id = current_user.get('user_id')
        role_keys = await MenuDao.get_user_role_keys(query_db, user_id)
        if ADMIN_ROLE_KEY in role_keys:
            logger.debug(f"[鉴权] admin 通配放行 user_id={user_id} perm={perm}")
            return  # 超管通配放行
        perms = await MenuDao.get_perms_by_user_id(query_db, user_id)
        if perm not in perms:
            # 拒绝明细:用户实际拥有的 perms 列表,排错神器
            logger.warning(f"[鉴权] 权限不足 user_id={user_id} perm={perm} 拥有={perms}")
            raise PermissionException(message=f'无此接口权限: {perm}')
        logger.debug(f"[鉴权] 校验通过 user_id={user_id} perm={perm}")

    return Depends(_check_interface_perm)