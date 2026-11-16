"""资产配置模块 DO(数据库对象):资产类别/配置模式/目标占比/基金映射。"""

from sqlalchemy import Boolean, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base_model import BaseModel


class AssetClass(BaseModel):
    """资产类别表(商品/债券/股票/现金等,用户自定义)。"""

    __tablename__ = 'asset_classes'
    __table_args__ = (
        Index('idx_asset_class_user', 'user_id'),
        {'comment': '资产类别表'},
    )

    asset_class_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='资产类别主键')
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='用户ID(逻辑关联 sys_user.user_id)')
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment='资产类别名称(如 股票)')
    description: Mapped[str | None] = mapped_column(String(200), nullable=True, comment='描述')
    color: Mapped[str | None] = mapped_column(String(20), nullable=True, comment='图表颜色')
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0', comment='排序顺序')


class AssetClassMode(BaseModel):
    """资产类别配置模式表(高配/标配/低配等,用户自定义)。"""

    __tablename__ = 'asset_class_modes'
    __table_args__ = (
        Index('idx_asset_mode_user', 'user_id'),
        {'comment': '资产类别配置模式表'},
    )

    mode_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='配置模式主键')
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='用户ID(逻辑关联 sys_user.user_id)')
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment='模式名称(如 标配)')
    description: Mapped[str | None] = mapped_column(String(200), nullable=True, comment='描述')
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false', comment='是否默认模式(同用户互斥)')


class AssetClassTarget(BaseModel):
    """资产类别目标占比表(每个配置模式下各资产类别的目标占比)。"""

    __tablename__ = 'asset_class_targets'
    __table_args__ = (
        Index('idx_asset_target_mode', 'mode_id'),
        Index('idx_asset_target_class', 'asset_class_id'),
        {'comment': '资产类别目标占比表'},
    )

    target_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='目标占比主键')
    mode_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='配置模式ID(逻辑关联 asset_class_modes)')
    asset_class_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='资产类别ID(逻辑关联 asset_classes)')
    target_ratio: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, comment='目标占比(百分比,如 20.00 表示 20%)')


class FundAssetMapping(BaseModel):
    """基金到资产类别的映射表(用户手动将持仓基金归入资产类别)。"""

    __tablename__ = 'fund_asset_mappings'
    __table_args__ = (
        UniqueConstraint('user_id', 'fund_id', name='uk_user_fund_mapping'),
        Index('idx_fund_mapping_class', 'asset_class_id'),
        {'comment': '基金到资产类别的映射表'},
    )

    mapping_id: Mapped[int] = mapped_column(primary_key=True, nullable=False, autoincrement=True, comment='映射主键')
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='用户ID(逻辑关联 sys_user.user_id)')
    fund_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='基金ID(逻辑关联 fund)')
    asset_class_id: Mapped[int] = mapped_column(Integer, nullable=False, comment='资产类别ID(逻辑关联 asset_classes)')
