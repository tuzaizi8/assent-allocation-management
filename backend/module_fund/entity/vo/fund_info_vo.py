"""基金管理模块 VO(请求与视图模型):基金详细信息管理。

查询模型照 FundNavQueryModel 范式:直接继承 BaseModel 自带分页字段,
**不得继承 PageResponseModel**(响应模型的 rows/total/hasNext 是必填字段,
当 Query 参数解析会报 Field required,2026-10-12 实证)。
"""

from pydantic import BaseModel, ConfigDict, Field, alias_generators


class FundInfoPageQueryModel(BaseModel):
    """详情分页查询模型(代码模糊搜索)。"""

    model_config = ConfigDict(alias_generator=alias_generators.to_camel, populate_by_name=True)

    keyword: str | None = Field(default=None, max_length=20, description='基金代码模糊搜索')
    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=10, description='每页记录数')


class FundInfoCreateModel(BaseModel):
    """手动新增请求模型:仅需基金代码,档案由同花顺回源抓取。"""

    model_config = ConfigDict(alias_generator=alias_generators.to_camel, populate_by_name=True)

    fund_code: str = Field(max_length=20, description='基金代码')
