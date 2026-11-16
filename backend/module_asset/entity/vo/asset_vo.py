"""资产配置模块 VO(视图对象):资产类别/配置模式/目标占比/基金映射请求模型。"""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class AssetClassModel(BaseModel):
    """资产类别表对应 Pydantic 模型(基础 VO)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str | None = Field(default=None, max_length=50, description='资产类别名称')
    description: str | None = Field(default=None, max_length=200, description='描述')
    color: str | None = Field(default=None, max_length=20, description='图表颜色')
    sort_order: int | None = Field(default=0, description='排序顺序')


class AssetClassAddModel(AssetClassModel):
    """新增资产类别模型。"""

    name: str = Field(min_length=1, max_length=50, description='资产类别名称')


class AssetClassEditModel(AssetClassAddModel):
    """编辑资产类别模型。"""

    asset_class_id: int = Field(description='资产类别主键')


class AssetClassModeModel(BaseModel):
    """配置模式表对应 Pydantic 模型(基础 VO)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str | None = Field(default=None, max_length=50, description='模式名称')
    description: str | None = Field(default=None, max_length=200, description='描述')
    is_default: bool | None = Field(default=False, description='是否默认模式')


class AssetClassModeAddModel(AssetClassModeModel):
    """新增配置模式模型。"""

    name: str = Field(min_length=1, max_length=50, description='模式名称')


class AssetClassModeEditModel(AssetClassModeAddModel):
    """编辑配置模式模型。"""

    mode_id: int = Field(description='配置模式主键')


class AssetClassTargetModel(BaseModel):
    """单条目标占比(批量更新的元素)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    asset_class_id: int = Field(description='资产类别主键')
    target_ratio: float = Field(ge=0, le=100, description='目标占比(百分比)')


class AssetClassTargetBatchModel(BaseModel):
    """批量更新目标占比请求模型(全量替换语义)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    targets: list[AssetClassTargetModel] = Field(default_factory=list, description='目标占比全集')


class FundMappingModel(BaseModel):
    """基金映射请求模型。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    fund_id: int = Field(description='基金主键')
    asset_class_id: int = Field(description='资产类别主键')
