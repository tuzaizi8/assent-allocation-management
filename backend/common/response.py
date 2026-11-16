"""响应模型定义

基于 Pydantic 定义统一响应结构：
- ResponseBaseModel: 响应基类（code/msg/success/time）
- CrudResponseModel: 增删改操作响应（is_success/message/result）
- DataResponseModel[T]: 单对象数据响应（泛型 data 字段）
- PageModel[T]: 分页模型（rows/page_num/page_size/total/has_next）
- PageResponseModel[T]: 分页响应模型（合并分页字段 + 基类字段）
- DynamicResponseModel[T]: 动态响应模型（把泛型字段平铺到顶层）
"""
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, create_model
from pydantic.alias_generators import to_camel
from typing_extensions import Self

from common.constants import HttpStatusConstant

# 泛型类型变量，用于参数化响应模型
T = TypeVar('T')


class ResponseBaseModel(BaseModel):
    """响应模型基类

    所有统一响应都包含这 4 个字段：
    - code: 业务状态码（200 成功 / 601 业务失败 / 401 未认证 / 403 禁止 / 500 系统错误）
    - msg: 人类可读的响应信息
    - success: 是否成功（前端快捷判断用，避免每次都比较 code）
    - time: 响应时间戳（排查耗时、对账用）
    """

    code: int = Field(default=HttpStatusConstant.SUCCESS, description='响应码')
    msg: str = Field(default='操作成功', description='响应信息')
    success: bool = Field(default=True, description='响应是否成功')
    time: datetime = Field(default_factory=datetime.now, description='响应时间')


class CrudResponseModel(BaseModel):
    """增删改操作响应模型

    用于 Service 层返回「操作是否成功」的语义化结果，
    不含 code/msg（由 ResponseUtil 在外层包装）。
    """

    is_success: bool = Field(description='操作是否成功')
    message: str = Field(description='响应信息')
    result: Any | None = Field(default=None, description='响应结果')


class DataResponseModel(ResponseBaseModel, Generic[T]):
    """数据响应模型（泛型）

    用于返回单个对象，例如：
        DataResponseModel[UserModel]  → {code, msg, success, time, data: UserModel}
    """

    data: T = Field(description='响应数据')


class PageModel(BaseModel, Generic[T]):
    """分页模型

    仅包含分页相关字段，不包含响应码。
    配合 PageResponseModel 使用，或单独作为内层 data。
    """

    model_config = ConfigDict(alias_generator=to_camel,populate_by_name=True)

    rows: list[T] = Field(description='记录列表')
    page_num: int = Field(description='当前页码')
    page_size: int = Field(description='每页记录数')
    total: int = Field(description='总记录数')
    has_next: bool = Field(description='是否有下一页')


class PageResponseModel(PageModel, ResponseBaseModel, Generic[T]):
    """分页响应模型

    多继承合并：分页字段（rows/page_num...）+ 基类字段（code/msg/success/time）。
    注意继承顺序：PageModel 在前，ResponseBaseModel 在后，
    确保 alias_generator（驼峰别名）生效。
    """


class DynamicResponseModel(ResponseBaseModel, Generic[T]):
    """动态响应模型

    与 DataResponseModel[T] 把数据包在 data 字段不同，
    DynamicResponseModel[T] 会把 T 的字段**平铺到顶层**，
    与基类字段合并成一个扁平模型。

    用法：
        DynamicResponseModel[UserModel]  → {code, msg, success, time, user_id, username, ...}

    适用于 OpenAPI 文档需要把业务字段直接展示在顶层（而非嵌套在 data 下）的场景。
    """

    model_config = ConfigDict(alias_generator=to_camel,populate_by_name=True)

    def __class_getitem__(cls, item: Any) -> Any | Self:
        """当使用 DynamicResponseModel[Item] 语法时，动态创建一个包含所有字段的新模型"""
        # 检查是否已经为该类型创建了模型（缓存避免重复 create_model）
        if not hasattr(cls, '_cached_models'):
            cls._cached_models = {}

        if item in cls._cached_models:
            return cls._cached_models[item]

        # 检查 item 是否为 Pydantic 模型（只有模型才能提取字段）
        if not hasattr(item, 'model_fields'):
            raise TypeError(f'{item} 不是一个Pydantic模型，请使用Pydantic模型作为泛型参数')

        # 获取 ResponseBaseModel 的字段
        base_fields = {}
        for field_name, field in cls.model_fields.items():
            base_fields[field_name] = (field.annotation, field)

        # 获取泛型类型 T 的字段
        item_fields = {}
        for field_name, field in item.model_fields.items():
            item_fields[field_name] = (field.annotation, field)

        # 合并所有字段（item 字段不会覆盖 base 字段，因为 base 在前）
        all_fields = {**base_fields, **item_fields}

        # 动态创建新模型
        new_model = create_model(
            f'DynamicResponseModel[{item.__name__}]',
            __base__=cls,
            __config__=cls.model_config,
            **all_fields,
        )

        # 缓存模型，下次直接返回
        cls._cached_models[item] = new_model

        return new_model