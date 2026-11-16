"""持仓模块 DO(数据库对象):用户基金持仓头表。"""

from sqlalchemy import CHAR, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel

# 持仓状态编码(字典 sys_position_status 的 dict_value 逐字对应,表语义出处):
# '部分赎回'目前无写入路径,字典保留该态供后续业务接入
POSITION_STATUS_NORMAL = '0'
POSITION_STATUS_PARTIAL_REDEEMED = '1'
POSITION_STATUS_FULLY_REDEEMED = '2'


class UserFundPosition(BaseModel):
    """用户基金持仓头表(按 user_id + fund_code 聚合所有买卖记录)。"""

    __tablename__ = 'user_fund_positions'
    # 业务最高频路径:按用户取持仓 + 按用户+基金定位 active 持仓(买入/赎回自动匹配)
    __table_args__ = (
        Index('idx_position_user_fund', 'user_id', 'fund_code'),
        {'comment': '用户基金持仓头表'},
    )

    position_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='持仓主键')
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='用户ID(逻辑关联 sys_user.user_id)')
    # 以基金代码而非 ID 关联:fund.code 全局唯一(含已删记录),免去建仓前"查基金拿 ID"的二次查询
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False, comment='基金代码(逻辑关联 fund.code,无外键)')
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=POSITION_STATUS_NORMAL, comment='持仓状态(0正常 1部分赎回 2全部赎回,字典 sys_position_status)')
    del_flag: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='删除标志(0存在 2删除,全额赎回后软删)')
