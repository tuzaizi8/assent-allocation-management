"""字典管理模块 VO(视图对象)。

包含字典类型与字典数据两套模型,全部开启驼峰别名转换。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class DictTypeModel(BaseModel):
    """字典类型表对应 Pydantic 模型(基础 VO)。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    dict_id: int | None = Field(default=None, description='字典主键')
    dict_name: str | None = Field(default=None, description='字典名称(如 用户性别)')
    dict_type: str | None = Field(default=None, description='字典类型(如 sys_user_sex,唯一)')
    status: Literal['0', '1'] | None = Field(default='0', description='状态(0正常 1停用)')
    create_by: str | None = Field(default=None, description='创建者')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
    remark: str | None = Field(default=None, description='备注')


class DictTypePageQueryModel(DictTypeModel):
    """字典类型分页查询模型。"""

    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=10, description='每页记录数')


class DictTypeAddModel(DictTypeModel):
    """新增字典类型模型(继承完整模型,含审计字段——对齐 UserAddModel 范式)。"""

    dict_name: str = Field(min_length=1, max_length=100, description='字典名称')
    dict_type: str = Field(min_length=1, max_length=100, description='字典类型(建议 sys_ 前缀)')
    status: Literal['0', '1'] = Field(default='0', description='状态(0正常 1停用)')


class DictTypeEditModel(DictTypeAddModel):
    """编辑字典类型模型。"""

    dict_id: int = Field(description='字典主键')


class DeleteDictTypeModel(BaseModel):
    """删除字典类型模型。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    dict_ids: str = Field(description='需要删除的字典主键(逗号分隔)')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')


class DictDataModel(BaseModel):
    """字典数据表对应 Pydantic 模型(基础 VO)。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    dict_code: int | None = Field(default=None, description='字典编码')
    dict_sort: int | None = Field(default=0, description='显示排序')
    dict_label: str | None = Field(default=None, description='字典标签(如 男)')
    dict_value: str | None = Field(default=None, description='字典键值(如 0,恒为 string 契约)')
    dict_type: str | None = Field(default=None, description='字典类型(关联 sys_dict_type)')
    css_class: str | None = Field(default=None, description='前端样式类(如 tag-primary,07 第五节契约)')
    status: Literal['0', '1'] | None = Field(default='0', description='状态(0正常 1停用)')
    create_by: str | None = Field(default=None, description='创建者')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
    remark: str | None = Field(default=None, description='备注')


class DictDataAddModel(DictDataModel):
    """新增字典数据模型(继承完整模型,含审计字段——对齐 UserAddModel 范式)。"""

    dict_type: str = Field(min_length=1, max_length=100, description='字典类型')
    dict_label: str = Field(min_length=1, max_length=100, description='字典标签')
    dict_value: str = Field(min_length=1, max_length=100, description='字典键值')
    dict_sort: int = Field(default=0, description='显示排序')
    css_class: str | None = Field(default=None, max_length=100, description='前端样式类(选填)')
    status: Literal['0', '1'] = Field(default='0', description='状态(0正常 1停用)')


class DictDataEditModel(DictDataAddModel):
    """编辑字典数据模型。"""

    dict_code: int = Field(description='字典编码')


class DeleteDictDataModel(BaseModel):
    """删除字典数据模型。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    dict_ids: str = Field(description='需要删除的字典编码(逗号分隔)')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
