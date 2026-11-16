"""持仓分析模块 VO(视图对象):交易导入确认请求模型。

分析/收益率类接口的查询参数(日期区间/采样间隔/基准)均为标量 Query 参数,
在 Controller 层直接声明,无需独立 VO。
"""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ImportTransactionRecordModel(BaseModel):
    """预览确认导入的单条交易记录(与预览响应的记录结构一致)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    fund_code: str = Field(description='基金代码')
    fund_name: str = Field(default='', description='基金名称')
    date: str = Field(description='交易日期(ISO 格式)')
    type: str = Field(description='交易类型(买入/赎回)')
    # 分红行才有值(红利再投资/现金分红):账本没有独立分红表,落库时靠它把标签写进备注
    dividend: str = Field(default='', description='分红行标签(红利再投资/现金分红),非分红行为空')
    amount: float = Field(default=0, description='确认金额(元)')
    shares: float = Field(default=0, description='确认份额')
    unit_price: float = Field(default=0, description='单价(=金额/份额)')
    fee: float = Field(default=0, description='手续费')
    order_no: str | None = Field(default=None, description='订单号')
    nav_pending: bool = Field(default=False, description='净值未发布、份额待确认(列表式截图)')
    remark: str | None = Field(default=None, description='备注')


class TransactionConfirmModel(BaseModel):
    """交易明细导入确认请求模型。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    confirmed: bool = Field(description='是否确认导入(False 视为取消)')
    # 本次预览选中的适配器 key(预览响应的 summary.adapter 原样回传):决定判重的**平台作用域**。
    # 刻意必填、且未知 key 报错——漏传会让判重失效,把重复记录当新数据累加,宁可当场失败。
    adapter: str = Field(description='平台适配器 key(如 alipay / tiantian,来自预览 summary.adapter)')
    records: list[ImportTransactionRecordModel] = Field(default_factory=list, description='预览后确认的交易记录')
