"""持仓模块 VO(视图对象):快照分页查询模型。"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class SnapshotPageQueryModel(BaseModel):
    """快照分页查询模型(与 PositionPageQueryModel 同款:驼峰别名 + 允许按字段名传)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    page_num: int = Field(default=1, ge=1, description='当前页码')
    page_size: int = Field(default=10, ge=1, le=100, description='每页记录数')
    start_date: date | None = Field(default=None, description='起始日期(默认结束日前 90 天)')
    end_date: date | None = Field(default=None, description='结束日期(默认今天)')
