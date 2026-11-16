"""持仓模块 DO(数据库对象):每日持仓快照表。"""

from sqlalchemy import Date, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class DailyPortfolioSnapshot(BaseModel):
    """每日基金持仓快照表(预计算每日份额/净值/市值,加速 TWR/MWR 分析)。"""

    __tablename__ = 'daily_portfolio_snapshots'
    # 分析查询路径:按用户 + 日期范围取快照
    # (user_id, 日期, 基金) 唯一:同一天同一只基金只能一行。写入方(全量重建/区间生成/交易后回填)
    # 是「先清空再批量插」或「先查再插」,并发时会各插一份(2026-09-18 实测被写成 3 份,页面
    # 基金数与市值放大 3 倍且列表接口 500);唯一约束与 SnapshotService._try_lock_user_writes
    # 的写入互斥锁一起构成双保险,漏网时直接报错而不是静默产生重复。
    # 存量库需手动执行 DDL:
    #   CREATE UNIQUE INDEX uk_snapshot_user_date_fund
    #     ON daily_portfolio_snapshots (user_id, snapshot_date, fund_code);
    __table_args__ = (
        Index('idx_snapshot_user_date', 'user_id', 'snapshot_date'),
        UniqueConstraint('user_id', 'snapshot_date', 'fund_code', name='uk_snapshot_user_date_fund'),
        {'comment': '每日基金持仓快照表'},
    )

    snapshot_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='快照主键')
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='用户ID(逻辑关联 sys_user.user_id)')
    snapshot_date: Mapped[Date] = mapped_column(Date, nullable=False, comment='快照日期')
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False, comment='基金代码')
    shares: Mapped[float] = mapped_column(Float, nullable=False, server_default='0', comment='当日持有份额')
    nav: Mapped[float] = mapped_column(Float, nullable=False, server_default='0', comment='当日单位净值(市值计算永远用 unit_nav)')
    market_value: Mapped[float] = mapped_column(Float, nullable=False, server_default='0', comment='当日市值(=份额×单位净值)')
