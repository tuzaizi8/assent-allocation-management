"""持仓模块 DO(数据库对象):每日现金流水表。"""

from sqlalchemy import Date, Float, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class DailyCashFlow(BaseModel):
    """每日现金流水表(预计算每日净现金流与累计净投入,加速 MWR 分析)。"""

    __tablename__ = 'daily_cash_flows'
    # (user_id, 日期) 唯一:每天只能一行。与快照表同源的问题:并发重建时「先清空再批量插」各插一份
    # (2026-09-18 实测被写成 2 份),而快照列表按「同日一行现金流」取累计净投入的标量子查询遇到
    # 多行会直接抛 CardinalityViolationError;唯一约束 + SnapshotService._try_lock_user_writes
    # 的写入互斥锁双保险。
    # 存量库需手动执行 DDL:
    #   CREATE UNIQUE INDEX uk_cash_flow_user_date ON daily_cash_flows (user_id, flow_date);
    __table_args__ = (
        Index('idx_cash_flow_user_date', 'user_id', 'flow_date'),
        UniqueConstraint('user_id', 'flow_date', name='uk_cash_flow_user_date'),
        {'comment': '每日现金流水表'},
    )

    flow_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='流水主键')
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='用户ID(逻辑关联 sys_user.user_id)')
    flow_date: Mapped[Date] = mapped_column(Date, nullable=False, comment='流水日期')
    cash_flow: Mapped[float] = mapped_column(Float, nullable=False, server_default='0', comment='当日净现金流(买入为负,赎回为正)')
    cumulative_invested: Mapped[float] = mapped_column(Float, nullable=False, server_default='0', comment='累计净投入(累计买入-累计赎回,含区间前历史交易)')
