"""菜单管理模块 VO(视图对象)。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class MenuModel(BaseModel):
    """菜单表对应 Pydantic 模型(基础 VO)。"""

    # 开启驼峰别名转换 + 支持从 ORM 对象读取(from_attributes)
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    menu_id: int | None = Field(default=None, description='菜单ID')
    menu_name: str | None = Field(default=None, description='菜单名称')
    parent_id: int | None = Field(default=0, description='父菜单ID(0=根)')
    order_num: int | None = Field(default=0, description='显示顺序')
    path: str | None = Field(default=None, description='路由地址')
    component: str | None = Field(default=None, description='组件路径')
    perms: str | None = Field(default=None, description='权限标识')
    menu_type: Literal['M', 'C', 'F'] | None = Field(default=None, description='菜单类型(M目录 C菜单 F按钮)')
    icon: str | None = Field(default=None, description='菜单图标')
    visible: Literal['0', '1'] | None = Field(default='0', description='显示状态(0显示 1隐藏)')
    status: Literal['0', '1'] | None = Field(default='0', description='菜单状态(0正常 1停用)')
    create_by: str | None = Field(default=None, description='创建者')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
    remark: str | None = Field(default=None, description='备注')


class MenuQueryModel(BaseModel):
    """菜单列表查询模型(树形展示不分页)。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    menu_name: str | None = Field(default=None, description='菜单名称(模糊过滤)')


class MenuAddModel(MenuModel):
    """新增菜单模型。"""


class MenuEditModel(MenuModel):
    """编辑菜单模型。"""
