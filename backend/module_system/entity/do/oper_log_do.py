"""操作日志 DO(数据库对象)。"""

from datetime import datetime

from sqlalchemy import Index, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from common.constants import LogCategory
from db.database import Base


class SysOperLog(Base):
    """操作日志表(字段与 @Log 注解产出对齐)。"""

    __tablename__ = 'sys_oper_log'
    # category+oper_time 复合:列表查询必过滤 category + 时间范围,消除全表扫;
    # oper_name:搜索前缀可走索引(前置 % 通配仍全扫,量级可容忍);
    # 存量库需手动执行 DDL
    __table_args__ = (
        Index('idx_oper_log_category_time', 'category', 'oper_time'),
        Index('idx_oper_log_oper_name', 'oper_name'),
        {'comment': '操作日志记录表'},
    )

    oper_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='日志主键')
    title: Mapped[str] = mapped_column(String(50), nullable=False, server_default='', comment='模块标题')
    # 枚举值见 BusinessType
    business_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default='0', comment='业务类型')
    method: Mapped[str] = mapped_column(String(200), nullable=False, server_default='', comment='方法名称')
    request_method: Mapped[str] = mapped_column(String(10), nullable=False, server_default='', comment='请求方式')
    # anonymous=未登录
    oper_name: Mapped[str] = mapped_column(String(50), nullable=False, server_default='', comment='操作人员')
    # 部门表落地前为空
    dept_name: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='部门名称')
    oper_url: Mapped[str] = mapped_column(String(255), nullable=False, server_default='', comment='请求URL')
    oper_ip: Mapped[str] = mapped_column(String(128), nullable=False, server_default='', comment='操作IP')
    oper_param: Mapped[str | None] = mapped_column(Text, nullable=True, comment='请求参数')
    json_result: Mapped[str | None] = mapped_column(Text, nullable=True, comment='返回结果')
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default='0', comment='操作状态')
    error_msg: Mapped[str | None] = mapped_column(String(2000), nullable=True, comment='错误消息')
    # Integer 而非 SmallInteger,防长请求溢出(超 32s)
    cost_time: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0', comment='消耗时间')
    oper_time: Mapped[datetime] = mapped_column(comment='操作时间')
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=LogCategory.OPERATION, comment='日志类别'
    )
