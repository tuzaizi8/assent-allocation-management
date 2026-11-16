"""角色管理模块 VO(视图对象)。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class RoleModel(BaseModel):
    """角色表对应 Pydantic 模型(基础 VO)。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    role_id: int | None = Field(default=None, description='角色ID')
    role_name: str | None = Field(default=None, description='角色名称')
    role_key: str | None = Field(default=None, description='角色权限字符串(如 admin/common)')
    role_sort: int | None = Field(default=0, description='显示顺序')
    data_scope: Literal['1', '2', '3', '4', '5'] | None = Field(
        default='1', description='数据范围(1全部 2自定义 3本部门 4本部门及以下 5仅本人)')
    status: Literal['0', '1'] | None = Field(default='0', description='角色状态(0正常 1停用)')
    del_flag: Literal['0', '2'] | None = Field(default='0', description='删除标志(0存在 2删除)')
    create_by: str | None = Field(default=None, description='创建者')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
    remark: str | None = Field(default=None, description='备注')
    admin: bool | None = Field(default=False, description='是否内置管理员角色')

    @model_validator(mode='after')
    def check_admin(self) -> 'RoleModel':
        """内置角色判定(role_id == 1 为 admin,权限体系通配锚点,禁删/禁改权限字符)。"""
        self.admin = self.role_id == 1
        return self


class RolePageQueryModel(RoleModel):
    """角色管理分页查询模型。"""

    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=10, description='每页记录数')


class RoleAddModel(RoleModel):
    """新增角色模型。"""

    menu_ids: list[int] = Field(default=[], description='绑定的菜单ID列表')


class RoleEditModel(RoleAddModel):
    """编辑角色模型。"""


class DeleteRoleModel(BaseModel):
    """删除角色模型。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    role_ids: str = Field(description='需要删除的角色ID(逗号分隔)')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
