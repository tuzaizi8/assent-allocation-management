"""持仓模块 DO(数据库对象):基金赎回记录表。"""

from sqlalchemy import CHAR, Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class RedemptionRecord(BaseModel):
    """基金赎回记录表(每次赎回一行,赎回净值按赎回日自动获取)。"""

    __tablename__ = 'redemption_records'
    __table_args__ = (
        Index('idx_redemption_position', 'position_id'),
        Index('idx_redemption_fund', 'fund_code'),
        Index('idx_redemption_user_fund', 'user_id', 'fund_code'),
        {'comment': '基金赎回记录表'},
    )

    redemption_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='赎回记录主键')
    position_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='持仓ID(逻辑关联 user_fund_positions)')
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='用户ID(逻辑关联 sys_user.user_id;持仓行被清空后流水仍有归属)')
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False, comment='基金代码(明细按基金代码匹配,跨持仓合并历史)')
    shares: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, comment='赎回份额')
    nav_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, comment='赎回净值(赎回日单位净值)')
    redemption_date: Mapped[Date] = mapped_column(Date, nullable=False, comment='赎回日期')
    status: Mapped[str] = mapped_column(
        CHAR(1), nullable=False, server_default='1', comment='确认状态(0待确认 1已确认):所选日期净值发布前录入的赎回待目标净值日公布后回填到账金额'
    )
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True, comment='到账金额(待确认时为空,确认后冗余=shares*nav_price)')
    del_flag: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='删除标志(0存在 2删除)')
