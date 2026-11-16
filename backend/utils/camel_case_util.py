"""驼峰命名转换工具。

把数据库 DO 对象或字典的 snake_case 字段名转成 camelCase，便于前端直接使用。
"""

from typing import Any

from sqlalchemy.orm import DeclarativeBase


class CamelCaseUtil:
    """snake_case → camelCase 转换工具。"""

    @classmethod
    def transform_result(cls, result: Any, exclude: set[str] | None = None) -> dict[str, Any]:
        """把单条查询结果转成驼峰命名的字典。

        :param result: SQLAlchemy DO 实例、字典、Row 对象、或 None
        :param exclude: 需要剔除的字段名集合（按 snake_case 原列名匹配，兼容误传驼峰名）
        :return: 驼峰命名的字典（result 为 None 时返回空字典）
        """
        if result is None:
            return {}

        # SQLAlchemy DO 实例：通过 __table__.columns 取字段名
        if isinstance(result, DeclarativeBase):
            data = {col.name: getattr(result, col.name) for col in result.__table__.columns}
        elif isinstance(result, dict):
            data = result
        else:
            # SQLAlchemy 2.0 Row 对象有 _mapping 属性
            data = dict(result._mapping) if hasattr(result, '_mapping') else dict(result)

        # snake_case → camelCase（exclude 命中 snake_case 或驼峰名均剔除）
        return {
            cls._to_camel(k): v
            for k, v in data.items()
            if not exclude or (k not in exclude and cls._to_camel(k) not in exclude)
        }

    @classmethod
    def _to_camel(cls, snake_str: str) -> str:
        """把单个字段名从 snake_case 转成 camelCase。

        :param snake_str: snake_case 字符串，如 user_name
        :return: camelCase 字符串，如 userName
        """
        parts = snake_str.split('_')
        return parts[0] + ''.join(word.capitalize() for word in parts[1:])