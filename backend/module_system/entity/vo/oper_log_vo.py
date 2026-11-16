"""操作日志模块 VO(视图对象)。

查询 + 删除模型(物理删除)。
所有模型默认开启驼峰别名转换:前端传 `pageNum`/`operName` 自动映射。
"""

from datetime import datetime

from common.constants import LogCategory
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class OperLogQueryModel(BaseModel):
    """操作日志分页查询模型(category 必传,分流操作/登录日志)。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    title: str | None = Field(default=None, description='模块标题(模糊匹配)')
    oper_name: str | None = Field(default=None, description='操作人员(模糊匹配)')
    status: int | None = Field(default=None, description='操作状态(0正常 1异常,精确)')
    category: str = Field(
        default=LogCategory.OPERATION, description=f'日志类别({LogCategory.OPERATION}/{LogCategory.LOGIN})'
    )
    begin_time: str | None = Field(default=None, description='开始时间(YYYY-MM-DD)')
    end_time: str | None = Field(default=None, description='结束时间(YYYY-MM-DD)')
    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=10, description='每页记录数')

class OperLogDeleteModel(BaseModel):
    """操作日志删除模型(路径参数为逗号分隔 ID 串)。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    oper_ids: str = Field(description='日志ID串(逗号分隔,如 "1,2,3")')


class OperLogDetailModel(BaseModel):
    """日志详情响应模型(全量含大字段,单查接口用)。"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    oper_id: int = Field(description='日志主键')
    title: str = Field(description='模块标题')
    business_type: int = Field(description='业务类型')
    method: str | None = Field(default=None, description='方法名称')
    request_method: str | None = Field(default=None, description='请求方式')
    oper_name: str = Field(description='操作人员')
    dept_name: str | None = Field(default=None, description='部门名称')
    oper_url: str = Field(description='请求URL')
    oper_ip: str = Field(description='操作IP')
    oper_param: str | None = Field(default=None, description='请求参数(JSON)')
    json_result: str | None = Field(default=None, description='返回结果(JSON,已截断)')
    status: int = Field(description='操作状态')
    error_msg: str | None = Field(default=None, description='错误消息')
    cost_time: int = Field(description='消耗时间(ms)')
    oper_time: datetime = Field(description='操作时间')
    category: str = Field(description='日志类别')
