"""基金模块 DO(数据库对象):指数净值历史表。"""

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class IndexNavHistory(BaseModel):
    """指数净值历史表(一行一个指数,nav_data 存完整历史行情)。"""

    __tablename__ = 'index_nav_history'
    __table_args__ = (
        UniqueConstraint('index_code', name='uk_index_nav_code'),
        {'comment': '指数净值历史表'},
    )

    index_nav_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='指数净值主键')
    index_code: Mapped[str] = mapped_column(String(20), nullable=False, comment='指数代码(Sina symbol,如 sh000300)')
    index_name: Mapped[str] = mapped_column(String(50), nullable=False, comment='指数名称(如 沪深300)')
    nav_data: Mapped[dict] = mapped_column(JSON, nullable=False, comment='行情数据(source+records,每条含 nav_date/close/open/high/low/volume/daily_yield)')
