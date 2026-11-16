"""角色模块 DO(数据库对象):角色表 + 角色/菜单、角色/部门关联表。"""

from sqlalchemy import CHAR, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel
from db.database import Base


class SysRole(BaseModel):
    """角色信息表。"""

    __tablename__ = 'sys_role'
    # role_key 精确匹配是登录权限装配高频路径;列表恒过滤 status+del_flag
    __table_args__ = (
        Index('idx_role_key', 'role_key'),
        Index('idx_role_status_del', 'status', 'del_flag'),
        {'comment': '角色信息表'},
    )

    # 种子数据手工指定 1/2,勿依赖自增
    role_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='角色ID')
    role_name: Mapped[str] = mapped_column(String(30), nullable=False, comment='角色名称')
    # 如 admin/common,CheckRoleInterfaceAuth 校验与权限通配的锚点
    role_key: Mapped[str] = mapped_column(String(100), nullable=False, comment='角色权限字符串')
    role_sort: Mapped[int] = mapped_column(nullable=False, comment='显示顺序')
    data_scope: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='1', comment='数据范围(1全部 2自定义 3本部门 4本部门及以下 5仅本人)')
    menu_check_strictly: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, server_default='1', comment='菜单树选择项是否关联显示')
    dept_check_strictly: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, server_default='1', comment='部门树选择项是否关联显示')
    status: Mapped[str] = mapped_column(CHAR(1), nullable=False, comment='角色状态(0正常 1停用)')
    del_flag: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='删除标志(0存在 2删除)')


class SysRoleMenu(Base):
    """角色和菜单关联表(纯联合主键,不继承 BaseModel——关联行无审计语义)。"""

    __tablename__ = 'sys_role_menu'
    # 联合主键 (role_id, menu_id) 已覆盖 role_id 前缀查询;
    # menu_id 单列索引支撑菜单删除前的引用计数(反查 menu_id)
    __table_args__ = (
        Index('idx_role_menu_menu', 'menu_id'),
        {'comment': '角色和菜单关联表'},
    )

    role_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, comment='角色ID')
    menu_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, comment='菜单ID')


class SysRoleDept(Base):
    """角色和部门关联表(预留:数据权限"自定义部门"级别用,当前无消费方)。"""

    __tablename__ = 'sys_role_dept'
    __table_args__ = {'comment': '角色和部门关联表'}

    role_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, comment='角色ID')
    dept_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, comment='部门ID')
