"""认证模块 VO(视图对象)。

LoginModel/RegisterModel 接受前端 camelCase 字段(alias_generator 自动映射),
AuthUserModel 输出前端 User 结构(id/email/firstName/lastName/role/permissions)。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class LoginModel(BaseModel):
    """登录请求模型（前端 login-form 发送 {email, password}）。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    email: str = Field(description='用户邮箱（登录账号）')
    password: str = Field(description='登录密码（明文，仅 TLS 通道传输）')


class RegisterModel(BaseModel):
    """注册请求模型（前端 register-form 发送 {email, password, nickName}）。

    2026-10-14 改:废弃姓/名双字段——sys_user 无独立姓名列,两字段拼接进
    nick_name 后读侧无法再拆分;改为单一 nick_name 直接落 nick_name 列。
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    email: str = Field(description='用户邮箱')
    password: str = Field(description='登录密码')
    nick_name: str = Field(
        min_length=1,
        max_length=30,
        description='昵称(落 sys_user.nick_name;读侧映射回 User.firstName 展示)',
    )


class AuthUserModel(BaseModel):
    """认证用户响应模型（对齐前端 User 类型，契约见《05-数据契约规范》）。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str = Field(description='用户ID（前端约定 string）')
    email: str | None = Field(default=None, description='用户邮箱')
    first_name: str = Field(default='', description='名（映射 nick_name）')
    last_name: str = Field(default='', description='姓（sys_user 无此列，暂空）')
    role: Literal['ADMIN', 'USER'] = Field(description='角色（user_id==1 为 ADMIN）')
    permissions: list[str] = Field(description='权限标识列表')


class ProfileModel(BaseModel):
    """个人资料响应(自助页:可编辑区 + 只读区)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    user_name: str = Field(description='登录账号(注册时即邮箱,只读)')
    nick_name: str | None = Field(default=None, description='用户昵称(可改)')
    email: str | None = Field(default=None, description='邮箱(登录账号,只读)')
    phonenumber: str | None = Field(default=None, description='手机号码(可改)')
    role: Literal['ADMIN', 'USER'] = Field(description='角色(与 /auth/me 同源判定)')
    create_time: datetime | None = Field(default=None, description='注册时间(只读)')
    login_date: datetime | None = Field(default=None, description='最后登录时间(只读)')
    pwd_update_date: datetime | None = Field(default=None, description='上次修改密码时间(只读)')


class ProfileUpdateModel(BaseModel):
    """自助修改基本资料。

    只声明昵称与手机号两个字段是**结构性防线**:邮箱/user_name/角色/状态不在此模型里,
    改资料的 SQL 参数就永远构造不出这些列,不依赖"记得别传"这种人为约束。
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    nick_name: str = Field(min_length=1, max_length=30, description='用户昵称(sys_user.nick_name 非空且 30 字上限)')
    phonenumber: str | None = Field(default=None, max_length=11, description='手机号码(可空,与用户管理同口径)')


class PasswordUpdateModel(BaseModel):
    """自助修改密码(原密码校验 + 新旧不得相同)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    old_password: str = Field(min_length=1, description='原密码')
    new_password: str = Field(min_length=5, description='新密码(沿用注册侧最小长度口径)')

    @model_validator(mode='after')
    def check_new_differs(self) -> 'PasswordUpdateModel':
        """新旧相同直接拦在入参层:否则"改密成功"其实等于没改,用户还会被踢下线。"""
        if self.old_password == self.new_password:
            raise ValueError('新密码不能与原密码相同')
        return self
