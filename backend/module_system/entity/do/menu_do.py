"""菜单模块 DO(数据库对象):菜单权限表(perms 唯一真相源)。"""

from sqlalchemy import CHAR, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class SysMenu(BaseModel):
    """菜单权限表(M目录 C菜单 F按钮三态)。"""

    __tablename__ = 'sys_menu'
    # 列表恒 order(parent_id, order_num)——复合索引消 filesort;
    # getRouters 恒过滤 status='0'
    __table_args__ = (
        Index('idx_menu_parent_order', 'parent_id', 'order_num'),
        Index('idx_menu_status', 'status'),
        {'comment': '菜单权限表'},
    )

    # 种子按 1/100/1000+ 分段手工指定,勿依赖自增
    menu_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='菜单ID')
    menu_name: Mapped[str] = mapped_column(String(50), nullable=False, comment='菜单名称')
    parent_id: Mapped[int | None] = mapped_column(nullable=True, server_default='0', comment='父菜单ID(0=根)')
    order_num: Mapped[int | None] = mapped_column(nullable=True, server_default='0', comment='显示顺序')
    # 须与前端 paths.ts 已注册路由对齐,否则菜单点击 404
    path: Mapped[str | None] = mapped_column(String(200), nullable=True, server_default='', comment='路由地址')
    component: Mapped[str | None] = mapped_column(String(255), nullable=True, comment='组件路径')
    query: Mapped[str | None] = mapped_column(String(255), nullable=True, comment='路由参数')
    route_name: Mapped[str | None] = mapped_column(String(50), nullable=True, server_default='', comment='路由名称')
    is_frame: Mapped[int | None] = mapped_column(nullable=True, server_default='1', comment='是否为外链(0是 1否)')
    is_cache: Mapped[int | None] = mapped_column(nullable=True, server_default='0', comment='是否缓存(0缓存 1不缓存)')
    menu_type: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='', comment='菜单类型(M目录 C菜单 F按钮)')
    visible: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='是否显示(0显示 1隐藏)')
    status: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='菜单状态(0正常 1停用)')
    # 权限体系唯一真相源,三段式如 system:user:list
    perms: Mapped[str | None] = mapped_column(String(100), nullable=True, comment='权限标识')
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True, server_default='#', comment='菜单图标')
