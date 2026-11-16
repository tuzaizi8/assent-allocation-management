"""持仓模块 DO(数据库对象):基金买入记录表。"""

from sqlalchemy import CHAR, Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class PurchaseRecord(BaseModel):
    """基金买入记录表(每次买入一行,份额与成本由购买金额/当日净值换算)。"""

    __tablename__ = 'purchase_records'
    __table_args__ = (
        Index('idx_purchase_position', 'position_id'),
        Index('idx_purchase_fund', 'fund_code'),
        Index('idx_purchase_user_fund', 'user_id', 'fund_code'),
        {'comment': '基金买入记录表'},
    )

    purchase_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='买入记录主键')
    position_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='持仓ID(逻辑关联 user_fund_positions)')
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='用户ID(逻辑关联 sys_user.user_id;持仓行被清空后流水仍有归属)')
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False, comment='基金代码(明细按基金代码匹配,跨持仓合并历史)')
    shares: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, comment='买入份额(=购买金额/买入日单位净值)')
    cost_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, comment='买入成本单价(买入日单位净值)')
    purchase_date: Mapped[Date] = mapped_column(Date, nullable=False, comment='买入日期')
    status: Mapped[str] = mapped_column(
        CHAR(1), nullable=False, server_default='1', comment='确认状态(0待确认 1已确认):所选日期净值发布前录入的交易待目标净值日公布后回填'
    )
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True, comment='买入金额(待确认时先记用户输入,确认后冗余=shares*cost_price)')
