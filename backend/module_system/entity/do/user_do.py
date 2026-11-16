"""用户管理模块 DO(数据库对象)。"""

from datetime import datetime

from sqlalchemy import CHAR, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel

from db.database import Base


class SysUser(BaseModel):
    """用户信息表。"""

    __tablename__ = 'sys_user'
    # email 精确匹配是登录/注册查重高频路径;列表恒过滤 status+del_flag
    __table_args__ = (
        Index('idx_user_email', 'email'),
        Index('idx_user_status_del', 'status', 'del_flag'),
        {'comment': '用户信息表'},
    )

    user_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='用户ID')
    dept_id: Mapped[int | None] = mapped_column(comment='部门ID')
    user_name: Mapped[str] = mapped_column(String(30), nullable=False, comment='用户账号')
    nick_name: Mapped[str] = mapped_column(String(30), nullable=False, comment='用户昵称')
    user_type: Mapped[str | None] = mapped_column(String(2), nullable=True, server_default='00', comment='用户类型(00系统用户)')
    email: Mapped[str | None] = mapped_column(String(50), nullable=True, server_default='', comment='用户邮箱')
    phonenumber: Mapped[str | None] = mapped_column(String(11), nullable=True, server_default='', comment='手机号码')
    sex: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='用户性别(0男 1女 2未知)')
    avatar: Mapped[str | None] = mapped_column(String(100), nullable=True, server_default='', comment='头像地址')
    password: Mapped[str | None] = mapped_column(String(100), nullable=True, server_default='', comment='密码')
    status: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='帐号状态(0正常 1停用)')
    del_flag: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='删除标志(0存在 2删除)')
    login_ip: Mapped[str | None] = mapped_column(String(128), nullable=True, server_default='', comment='最后登录IP')
    login_date: Mapped[datetime | None] = mapped_column(comment='最后登录时间')
    pwd_update_date: Mapped[datetime | None] = mapped_column(comment='密码最后更新时间')


class SysUserRole(Base):
    """用户和角色关联表(纯联合主键,不继承 BaseModel——关联行无审计语义)。"""

    __tablename__ = 'sys_user_role'
    # 联合主键 (user_id, role_id) 已覆盖 user_id 前缀查询;
    # role_id 单列索引支撑 getRouters 的 role_id join 反向探测
    __table_args__ = (
        Index('idx_user_role_role', 'role_id'),
        {'comment': '用户和角色关联表'},
    )

    user_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, comment='用户ID')
    role_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, comment='角色ID')
