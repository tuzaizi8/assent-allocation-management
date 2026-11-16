"""
所有业务表都继承此基类，自动获得审计字段：
- create_by: 创建者
- create_time: 创建时间
- update_by: 更新者
- update_time: 更新时间
- remark: 备注
"""
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base


class BaseModel(Base):
    """公共字段基类（审计字段）"""

    __abstract__ = True  # 声明为抽象类，不会创建表

    create_by: Mapped[str | None] = mapped_column(String(64), default='', comment='创建者')
    create_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    update_by: Mapped[str | None] = mapped_column(String(64), default='', comment='更新者')
    update_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    remark: Mapped[str | None] = mapped_column(String(500), default='', comment='备注')