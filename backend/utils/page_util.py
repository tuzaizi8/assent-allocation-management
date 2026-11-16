"""分页工具类。

封装 SQLAlchemy 2.0 异步分页查询逻辑。
"""

import math
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select

from common.response import PageModel
from utils.camel_case_util import CamelCaseUtil


class PageUtil:
    """分页工具类：统一封装分页查询逻辑。"""

    @classmethod
    async def paginate(
        cls,
        db: AsyncSession,
        query: Select,
        page_num: int = 1,
        page_size: int = 10,
        is_page: bool = False,
        exclude: set[str] | None = None,
    ) -> PageModel | list[dict[str, Any]]:
        """执行分页查询。

        :param db: 异步会话
        :param query: SQLAlchemy Select 查询对象（未执行）
        :param page_num: 当前页码，从 1 开始
        :param page_size: 每页记录数
        :param is_page: 是否开启分页；False 时返回全量列表
        :param exclude: 序列化时剔除的字段名集合（如 {'password'}，透传 CamelCaseUtil）
        :return: 开启分页返回 PageModel，否则返回 list[dict]
        """
        if is_page:
            # 1. count 子查询：把原 query 作为子查询，外层 count，避免与 distinct 冲突
            count_query = select(func.count('*')).select_from(query.subquery())
            total = (await db.execute(count_query)).scalar() or 0

            # 2. 给原 query 追加 offset/limit
            # .all() 取整行 Row(多列投影场景:scalars() 只返回首列标量,Row._mapping 才是字段 dict);
            # 单实体查询(select(DO)):Row 唯一元素是 DO 实例,须取 row[0] 恢复 scalars 语义
            # (单实体 Row._mapping 的键是实体名 'SysUser' 而非字段名,驼峰化后成 {sysUser: DO} 破坏契约)
            offset = (page_num - 1) * page_size
            page_query = query.offset(offset).limit(page_size)
            result = (await db.execute(page_query)).all()
            rows_raw = [
                row[0] if len(row) == 1 and isinstance(row[0], DeclarativeBase) else row
                for row in result
            ]

            # 3. DO 对象转 dict + 字段名转驼峰（按 exclude 剔除敏感列）
            rows = [CamelCaseUtil.transform_result(row, exclude=exclude) for row in rows_raw]

            # 4. 计算是否有下一页：总页数 > 当前页码
            has_next = math.ceil(total / page_size) > page_num if page_size > 0 else False

            return PageModel(
                rows=rows,
                page_num=page_num,
                page_size=page_size,
                total=total,
                has_next=has_next,
            )
        else:
            # 不分页：全量查询，返回 list[dict]
            result = (await db.execute(query)).scalars().all()
            return [CamelCaseUtil.transform_result(row, exclude=exclude) for row in result]