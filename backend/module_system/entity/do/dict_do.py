"""字典模块 DO(数据库对象):字典类型表 + 字典数据表。"""

from sqlalchemy import CHAR, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class SysDictType(BaseModel):
    """字典类型表(一种枚举一行,如 sys_user_sex)。"""

    __tablename__ = 'sys_dict_type'
    __table_args__ = (
        UniqueConstraint('dict_type', name='uk_dict_type'),
        {'comment': '字典类型表'},
    )

    dict_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='字典主键')
    dict_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='字典名称(如 用户性别)')
    dict_type: Mapped[str] = mapped_column(String(100), nullable=False, comment='字典类型(如 sys_user_sex,唯一)')
    status: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='状态(0正常 1停用)')


class SysDictData(BaseModel):
    """字典数据表(枚举的每个选项)。"""

    __tablename__ = 'sys_dict_data'
    # 字典消费最高频路径:dict_type 精确 + dict_sort 排序,复合索引一次覆盖过滤+排序
    __table_args__ = (
        Index('idx_dict_data_type_sort', 'dict_type', 'dict_sort'),
        {'comment': '字典数据表'},
    )

    dict_code: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='字典编码')
    dict_sort: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default='0', comment='显示排序')
    dict_label: Mapped[str] = mapped_column(String(100), nullable=False, comment='字典标签(如 男)')
    dict_value: Mapped[str] = mapped_column(String(100), nullable=False, comment='字典键值(如 0,恒为 string 契约)')
    dict_type: Mapped[str] = mapped_column(String(100), nullable=False, comment='字典类型(关联 sys_dict_type)')
    css_class: Mapped[str | None] = mapped_column(String(100), nullable=True, comment='前端样式类(如 tag-primary)')
    status: Mapped[str | None] = mapped_column(CHAR(1), nullable=True, server_default='0', comment='状态(0正常 1停用)')
