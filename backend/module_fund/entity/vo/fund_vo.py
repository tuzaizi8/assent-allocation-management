"""基金管理模块 VO(视图对象)。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class FundModel(BaseModel):
    """基金信息表对应 Pydantic 模型(基础 VO)。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    fund_id: int | None = Field(default=None, description='基金主键')
    code: str | None = Field(default=None, description='基金代码(6位数字)')
    name: str | None = Field(default=None, description='基金名称')
    fund_type: str | None = Field(default=None, description='基金类型(取自 AkShare fund_name_em,如 混合型-灵活/债券型-混合二级)')
    status: Literal['0', '1'] | None = Field(default='0', description='状态(0正常 1停用)')
    create_by: str | None = Field(default=None, description='创建者')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
    remark: str | None = Field(default=None, description='基金描述')


class FundPageQueryModel(FundModel):
    """基金分页查询模型。"""

    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=10, description='每页记录数')


class FundAddModel(FundModel):
    """新增基金模型(继承完整模型,含审计字段)。"""

    code: str = Field(min_length=1, max_length=20, description='基金代码')
    name: str = Field(min_length=1, max_length=100, description='基金名称')
    status: Literal['0', '1'] = Field(default='0', description='状态(0正常 1停用)')


class FundEditModel(FundAddModel):
    """编辑基金模型。"""

    fund_id: int = Field(description='基金主键')


class DeleteFundModel(BaseModel):
    """删除基金模型。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    fund_ids: str = Field(description='需要删除的基金主键(逗号分隔)')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')


class FundNavQueryModel(BaseModel):
    """基金净值分页查询模型(净值管理页列表用)。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    fund_code: str | None = Field(default=None, description='基金代码(模糊匹配)')
    fund_name: str | None = Field(default=None, description='基金名称(模糊匹配,JOIN fund 表)')
    sync_status: str | None = Field(
        default=None,
        description="同步状态(sys_index_sync_status 字典值:'1'已同步 '0'未同步 '2'已过期;未同步基金不在净值表,传'0'返回空页)",
    )
    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=10, description='每页记录数')
