"""字典模块 DAO(数据访问层)。

字典管理页(2026-08-27)扩充两表 CRUD;写操作只 flush 不 commit(事务由 Service 控制)。
契约见知识库《04-字典管理页》。
"""

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.response import PageModel
from module_system.entity.do.dict_do import SysDictData, SysDictType
from module_system.entity.vo.dict_vo import DictTypePageQueryModel
from utils.page_util import PageUtil


class DictDao:
    """字典模块数据访问层。"""

    # ==================== 字典类型查询 ====================

    @classmethod
    async def get_dict_type_by_type(cls, db: AsyncSession, dict_type: str) -> SysDictType | None:
        """按 dict_type 查启用状态的字典类型(消费侧查询的存在性校验)。"""
        result = (
            (
                await db.execute(
                    select(SysDictType).where(
                        SysDictType.dict_type == dict_type,
                        SysDictType.status == '0',
                    )
                )
            )
            .scalars()
            .first()
        )
        return result

    @classmethod
    async def get_dict_type_by_type_any_status(cls, db: AsyncSession, dict_type: str) -> SysDictType | None:
        """按 dict_type 查字典类型(不过滤 status——管理端校验用,停用类型也占名)。"""
        result = (
            (await db.execute(select(SysDictType).where(SysDictType.dict_type == dict_type)))
            .scalars()
            .first()
        )
        return result

    @classmethod
    async def get_dict_type_by_id(cls, db: AsyncSession, dict_id: int) -> SysDictType | None:
        """按主键查字典类型(不过滤 status——停用类型仍可编辑/详情,对齐用户页语义)。"""
        result = (
            (await db.execute(select(SysDictType).where(SysDictType.dict_id == dict_id)))
            .scalars()
            .first()
        )
        return result

    @classmethod
    async def get_dict_type_list(
        cls, db: AsyncSession, query_object: DictTypePageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict[str, Any]]:
        """根据查询参数获取字典类型分页列表(名称/类型模糊可选)。"""
        query = (
            select(SysDictType)
            .where(
                # 条件查询:参数非空才追加 where(动态 SQL)
                SysDictType.dict_name.like(f'%{query_object.dict_name}%') if query_object.dict_name else True,
                SysDictType.dict_type.like(f'%{query_object.dict_type}%') if query_object.dict_type else True,
                SysDictType.status == query_object.status if query_object.status else True,
            )
            .order_by(SysDictType.dict_id)
        )
        dict_type_list: PageModel | list[dict[str, Any]] = await PageUtil.paginate(
            db, query, query_object.page_num, query_object.page_size, is_page
        )
        return dict_type_list

    @classmethod
    async def get_dict_types_by_ids(cls, db: AsyncSession, dict_ids: list[int]) -> list[SysDictType]:
        """根据主键列表批量获取字典类型(批量删除前置校验用)。"""
        result = await db.execute(select(SysDictType).where(SysDictType.dict_id.in_(dict_ids)))
        return list(result.scalars().all())

    @classmethod
    async def count_data_by_dict_type(cls, db: AsyncSession, dict_type: str) -> int:
        """统计类型下的字典数据条数(类型删除保护用)。"""
        result = await db.execute(
            select(func.count()).select_from(SysDictData).where(SysDictData.dict_type == dict_type)
        )
        return result.scalar() or 0

    # ==================== 字典数据查询 ====================

    @classmethod
    async def get_dict_data_by_type(cls, db: AsyncSession, dict_type: str) -> list[SysDictData]:
        """查某类型的全部有效字典数据(按 dict_sort 排序)。"""
        result = await db.execute(
            select(SysDictData)
            .where(
                SysDictData.dict_type == dict_type,
                SysDictData.status == '0',
            )
            .order_by(SysDictData.dict_sort)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_dict_data_all_by_type(cls, db: AsyncSession, dict_type: str) -> list[SysDictData]:
        """查某类型的全部字典数据(管理端列表,不过滤 status,按 dict_sort 排序)。"""
        result = await db.execute(
            select(SysDictData).where(SysDictData.dict_type == dict_type).order_by(SysDictData.dict_sort)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_dict_data_by_code(cls, db: AsyncSession, dict_code: int) -> SysDictData | None:
        """按编码查字典数据(不过滤 status——停用项仍可编辑)。"""
        result = (
            (await db.execute(select(SysDictData).where(SysDictData.dict_code == dict_code)))
            .scalars()
            .first()
        )
        return result

    @classmethod
    async def get_dict_data_by_codes(cls, db: AsyncSession, dict_codes: list[int]) -> list[SysDictData]:
        """根据编码列表批量获取字典数据(批量删除前置校验用)。"""
        result = await db.execute(select(SysDictData).where(SysDictData.dict_code.in_(dict_codes)))
        return list(result.scalars().all())

    @classmethod
    async def get_dict_data_by_type_and_value(
        cls, db: AsyncSession, dict_type: str, dict_value: str
    ) -> SysDictData | None:
        """按类型+键值查字典数据(同类型内 value 唯一性校验用)。"""
        result = (
            (
                await db.execute(
                    select(SysDictData).where(
                        SysDictData.dict_type == dict_type,
                        SysDictData.dict_value == dict_value,
                    )
                )
            )
            .scalars()
            .first()
        )
        return result

    # ==================== 写(只 flush,事务由 Service 控制) ====================

    @classmethod
    async def add_dict_type_dao(cls, db: AsyncSession, dict_type: SysDictType) -> SysDictType:
        """新增字典类型(flush 回填自增主键)。"""
        db.add(dict_type)
        await db.flush()
        return dict_type

    @classmethod
    async def edit_dict_type_dao(cls, db: AsyncSession, dict_type: dict) -> None:
        """编辑字典类型(批量更新语法,dict 含 dict_id 作 where 条件)。"""
        await db.execute(update(SysDictType), [dict_type])

    @classmethod
    async def delete_dict_types_by_ids(cls, db: AsyncSession, dict_ids: list[int]) -> None:
        """物理删除字典类型(sys_dict_type 无 del_flag,同菜单页语义;WHERE IN 单条)。"""
        await db.execute(delete(SysDictType).where(SysDictType.dict_id.in_(dict_ids)))

    @classmethod
    async def add_dict_data_dao(cls, db: AsyncSession, dict_data: SysDictData) -> SysDictData:
        """新增字典数据(flush 回填自增编码)。"""
        db.add(dict_data)
        await db.flush()
        return dict_data

    @classmethod
    async def edit_dict_data_dao(cls, db: AsyncSession, dict_data: dict) -> None:
        """编辑字典数据(批量更新语法,dict 含 dict_code 作 where 条件)。"""
        await db.execute(update(SysDictData), [dict_data])

    @classmethod
    async def delete_dict_data_by_codes(cls, db: AsyncSession, dict_codes: list[int]) -> None:
        """物理删除字典数据(sys_dict_data 无 del_flag;WHERE IN 单条)。"""
        await db.execute(delete(SysDictData).where(SysDictData.dict_code.in_(dict_codes)))
