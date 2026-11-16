"""持仓模块 DO(数据库对象):用户分散度规则表。"""

from sqlalchemy import Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class PortfolioRule(BaseModel):
    """用户分散度规则表(一用户一条,买入前校验各类基金最大占比)。"""

    __tablename__ = 'portfolio_rules'
    __table_args__ = (
        UniqueConstraint('user_id', name='uk_portfolio_rule_user'),
        {'comment': '用户分散度规则表'},
    )

    rule_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='规则主键')
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='用户ID(逻辑关联 sys_user.user_id)')
    max_single_fund_ratio: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, server_default='0.20', comment='单只基金最大占比(小数)')
    max_equity_ratio: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, server_default='0.60', comment='股票基金最大占比(小数)')
    max_bond_ratio: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, server_default='0.40', comment='债券基金最大占比(小数)')
    max_hybrid_ratio: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, server_default='0.30', comment='混合基金最大占比(小数)')
    max_money_ratio: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, server_default='0.20', comment='货币基金最大占比(小数)')
