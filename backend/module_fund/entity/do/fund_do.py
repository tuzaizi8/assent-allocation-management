"""基金模块 DO(数据库对象):基金信息表。"""

from sqlalchemy import CHAR, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class Fund(BaseModel):
    """基金信息表。"""

    __tablename__ = 'fund'
    __table_args__ = (
        UniqueConstraint('code', name='uk_fund_code'),
        {'comment': '基金信息表'},
    )

    fund_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='基金主键')
    code: Mapped[str] = mapped_column(String(20), nullable=False, comment='基金代码(6位数字,唯一,含已删记录占用)')
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment='基金名称')
    fund_type: Mapped[str | None] = mapped_column(String(20), nullable=True, comment='基金类型(取自 AkShare fund_name_em,如 混合型-灵活/债券型-混合二级)')
    status: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='状态(0正常 1停用)')
    del_flag: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='删除标志(0存在 2删除)')
