"""用户管理模块 VO（视图对象）。

包含请求模型与响应模型，所有模型默认开启驼峰别名转换，
前端传 `userName` 自动映射到 `user_name`。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class UserModel(BaseModel):
    """用户表对应 Pydantic 模型（基础 VO）。"""

    # 开启驼峰别名转换 + 支持从 ORM 对象读取（from_attributes）
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    user_id: int | None = Field(default=None, description='用户ID')
    dept_id: int | None = Field(default=None, description='部门ID')
    user_name: str | None = Field(default=None, description='用户账号')
    nick_name: str | None = Field(default=None, description='用户昵称')
    user_type: str | None = Field(default=None, description='用户类型（00系统用户）')
    email: str | None = Field(default=None, description='用户邮箱')
    phonenumber: str | None = Field(default=None, description='手机号码')
    sex: Literal['0', '1', '2'] | None = Field(default=None, description='用户性别（0男 1女 2未知）')
    avatar: str | None = Field(default=None, description='头像地址')
    password: str | None = Field(default=None, description='密码')
    status: Literal['0', '1'] | None = Field(default=None, description='帐号状态（0正常 1停用）')
    del_flag: Literal['0', '2'] | None = Field(default=None, description='删除标志（0代表存在 2代表删除）')
    login_ip: str | None = Field(default=None, description='最后登录IP')
    login_date: datetime | None = Field(default=None, description='最后登录时间')
    pwd_update_date: datetime | None = Field(default=None, description='密码最后更新时间')
    create_by: str | None = Field(default=None, description='创建者')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
    remark: str | None = Field(default=None, description='备注')
    admin: bool | None = Field(default=False, description='是否为admin')

    @model_validator(mode='after')
    def check_admin(self) -> 'UserModel':
        """自动识别 admin 用户（user_id == 1）。"""
        if self.user_id == 1:
            self.admin = True
        else:
            self.admin = False
        return self


class UserPageQueryModel(UserModel):
    """用户管理分页查询模型。"""

    begin_time: str | None = Field(default=None, description='开始时间')
    end_time: str | None = Field(default=None, description='结束时间')
    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=10, description='每页记录数')


class UserAddModel(UserModel):
    """新增用户模型。"""

    role_ids: list[int] | None = Field(default=[], description='角色ID列表')
    post_ids: list[int] | None = Field(default=[], description='岗位ID列表')


class UserEditModel(UserAddModel):
    """编辑用户模型。"""

    role: list | None = Field(default=[], description='角色信息')


class DeleteUserModel(BaseModel):
    """删除用户模型。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    user_ids: str = Field(description='需要删除的用户ID（逗号分隔）')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')