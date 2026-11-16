"""持仓管理模块 VO(视图对象):持仓/买入/赎回请求模型 + 分散度规则模型。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class PositionCreateModel(BaseModel):
    """创建持仓(首次买入)请求模型。

    份额由系统按购买金额/买入日净值换算,前端只传金额。
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    fund_code: str = Field(min_length=1, max_length=20, description='基金代码')
    amount: float = Field(gt=0, description='购买金额(元)')
    purchase_date: date = Field(description='买入日期')
    # 下单时间在 15:00 之后:确认日顺延到下一交易日,与截图导入同一条线
    after_cutoff: bool = Field(default=False, description='是否 15:00 之后下单')
    remark: str | None = Field(default=None, max_length=500, description='备注')


class PurchaseRecordCreateModel(BaseModel):
    """分批买入请求模型(无 active 持仓时自动建仓)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    fund_code: str = Field(min_length=1, max_length=20, description='基金代码')
    amount: float = Field(gt=0, description='购买金额(元)')
    purchase_date: date = Field(description='买入日期')
    # 下单时间在 15:00 之后:确认日顺延到下一交易日,与截图导入同一条线
    after_cutoff: bool = Field(default=False, description='是否 15:00 之后下单')
    remark: str | None = Field(default=None, max_length=500, description='备注')


class RedemptionRecordCreateModel(BaseModel):
    """赎回请求模型(净值按赎回日自动获取)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    fund_code: str = Field(min_length=1, max_length=20, description='基金代码')
    shares: float = Field(gt=0, description='赎回份额')
    redemption_date: date = Field(description='赎回日期')
    # 同买入:15:00 之后下单按下一交易日净值成交(影响到账金额与份额扣减日)
    after_cutoff: bool = Field(default=False, description='是否 15:00 之后下单')
    remark: str | None = Field(default=None, max_length=500, description='备注')


class PositionPageQueryModel(BaseModel):
    """持仓分页查询模型。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    page_num: int = Field(default=1, ge=1, description='当前页码')
    page_size: int = Field(default=10, ge=1, le=100, description='每页记录数')
    status: str | None = Field(default=None, max_length=2, description='持仓状态精确匹配(0正常 1部分赎回 2全部赎回,字典 sys_position_status)')
    keyword: str | None = Field(default=None, max_length=50, description='基金名称/代码模糊搜索')
    is_page: bool = Field(default=True, description='是否分页(false 返回全量,简况卡片页用)')
    # 排序键与方向:三个键都是**派生指标**(份额×净值 / 结转后成本算出来的),SQL 里没有对应列,
    # 所以服务层取全量行、算完指标再排序切片;认不出的键回落默认(不报错,列表页不该因参数挂掉)
    sort_by: str | None = Field(default=None, description='排序字段(current_value 当前市值 / profit 持有收益 / profit_rate 持有收益率),缺省按当前市值')
    sort_order: str | None = Field(default=None, description='排序方向(desc 降序 / asc 升序),缺省 desc')


class TransactionPageQueryModel(BaseModel):
    """交易流水分页查询模型。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    page_num: int = Field(default=1, ge=1, description='当前页码')
    page_size: int = Field(default=10, ge=1, le=100, description='每页记录数')
    tx_type: str | None = Field(default=None, max_length=3, description='交易类型精确匹配(买入/赎回),不传返回全部类型')


class DeletePositionModel(BaseModel):
    """删除持仓模型。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    position_id: int = Field(description='持仓主键')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')


class PortfolioRuleModel(BaseModel):
    """分散度规则模型(一用户一条,查询无记录时返回默认值)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    max_single_fund_ratio: float = Field(default=0.20, ge=0, le=1, description='单只基金最大占比(小数)')
    max_equity_ratio: float = Field(default=0.60, ge=0, le=1, description='股票基金最大占比(小数)')
    max_bond_ratio: float = Field(default=0.40, ge=0, le=1, description='债券基金最大占比(小数)')
    max_hybrid_ratio: float = Field(default=0.30, ge=0, le=1, description='混合基金最大占比(小数)')
    max_money_ratio: float = Field(default=0.20, ge=0, le=1, description='货币基金最大占比(小数)')


class ValidationResultModel(BaseModel):
    """基金可添加性验证结果。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    valid: bool = Field(description='是否可添加')
    errors: list[str] = Field(default_factory=list, description='错误信息')
