"""基金管理模块 DO(数据库对象):基金详细信息表。

数据源为 akshare fund_info_ths(同花顺基金档案),返回「字段/值」两列键值对
且字段名随源站改版变动——宽表建列会被打碎,故用 JSONB 全量接收键值 dict。
与 fund 表仅按 fund_code 逻辑关联,无任何外键。
"""

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class FundInfo(BaseModel):
    """基金详细信息表(每只基金一行,info 存同花顺档案全量键值)。"""

    __tablename__ = 'fund_info'
    __table_args__ = (
        Index('uidx_fund_info_code', 'fund_code', unique=True),
        {'comment': '基金详细信息表'},
    )

    fund_info_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='基金详情主键')
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False, comment='基金代码(逻辑关联 fund.code,无外键)')
    info: Mapped[dict] = mapped_column(JSONB, nullable=False, comment='基金详细信息(同花顺档案全量键值对,字段名随源站变动)')
