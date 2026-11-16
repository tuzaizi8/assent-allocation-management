"""基金模块 DO(数据库对象):基金净值历史表。"""

from datetime import date

from sqlalchemy import JSON, Date, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class FundNavHistory(BaseModel):
    """基金净值历史表(一行一只基金,nav_data 存一份完整数据,两套视图按需读不同字段)。"""

    __tablename__ = 'fund_nav_history'
    # 查询路径:按基金代码取行 + 按更新时间判断新鲜度,复合索引一次覆盖
    __table_args__ = (
        Index('idx_fund_nav_code_updated', 'fund_code', 'update_time'),
        {'comment': '基金净值历史表'},
    )

    fund_nav_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='净值历史主键')
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False, comment='基金代码')
    nav_data: Mapped[dict] = mapped_column(JSON, nullable=False, comment='净值数据(source+records,每条含 nav_date/unit_nav/accum_nav/raw_accum_nav/daily_yield)')
    # 元数据冗余列:列表页窄投影与三态同步状态 SQL 谓词依赖它们,读路径因此不必解析 nav_data 大 JSON
    latest_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment='最新净值日期(冗余自 nav_data 最后一条)')
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment='净值记录条数(冗余自 nav_data.records 长度)')
