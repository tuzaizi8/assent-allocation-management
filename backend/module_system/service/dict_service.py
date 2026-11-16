"""字典模块 Service(业务逻辑层)。

字典管理页(2026-08-27)扩充两表 CRUD;契约见知识库《04-字典管理页》。
职责:业务校验(唯一性/种子保护/引用保护)+ 事务控制。
校验失败一律 ServiceWarning(code 601,前端 warning toast 透传)。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from common.response import CrudResponseModel, PageModel
from exceptions.exceptions import ServiceWarning
from module_system.dao.dict_dao import DictDao
from module_system.entity.do.dict_do import SysDictData, SysDictType
from module_system.entity.vo.dict_vo import (
    DeleteDictDataModel,
    DeleteDictTypeModel,
    DictDataAddModel,
    DictDataEditModel,
    DictTypeAddModel,
    DictTypeEditModel,
    DictTypePageQueryModel,
)
from utils.camel_case_util import CamelCaseUtil
from utils.log import logger

# 种子内置字典类型主键(1=用户性别 2=系统开关 3=通知类型,镜像前端 DictTag 消费)
SEED_DICT_TYPE_IDS = {1, 2, 3}
# 种子内置字典数据编码(1-7,见 db/init_data.py 的 SEED_DICT_DATA)
SEED_DICT_DATA_CODES = set(range(1, 8))


class DictService:
    """字典模块服务层。"""

    # ---------- 消费侧查询(前端 useDict) ----------

    @classmethod
    async def get_dict_data_by_type_services(cls, db: AsyncSession, dict_type: str) -> list[dict]:
        """按类型返回字典选项列表(前端 DictOption 结构,camelCase)。

        契约:类型不存在返回空数组(容错,不抛 601)——与前端 mock 行为一致。
        """
        # 类型不存在/已停用 → 空数组(前端 .find 天然容错)
        dict_type_row = await DictDao.get_dict_type_by_type(db, dict_type)
        if not dict_type_row:
            return []
        data_rows = await DictDao.get_dict_data_by_type(db, dict_type)
        return [
            {
                'dictLabel': row.dict_label,
                'dictValue': row.dict_value,
                'dictType': row.dict_type,
                'cssClass': row.css_class or '',
            }
            for row in data_rows
        ]

    # ---------- 管理端:字典类型 ----------

    @classmethod
    async def get_dict_type_list_services(
        cls, query_db: AsyncSession, query_object: DictTypePageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict]:
        """获取字典类型分页列表。"""
        return await DictDao.get_dict_type_list(query_db, query_object, is_page)

    @classmethod
    async def get_dict_type_detail_services(cls, query_db: AsyncSession, dict_id: int) -> dict:
        """获取字典类型详情。"""
        dict_type = await DictDao.get_dict_type_by_id(query_db, dict_id)
        if dict_type is None:
            raise ServiceWarning(message='字典类型不存在')
        return CamelCaseUtil.transform_result(dict_type)

    @classmethod
    async def _check_dict_type_unique(
        cls, query_db: AsyncSession, dict_type: str, exclude_id: int = -1
    ) -> None:
        """字典类型唯一性校验(编辑时排除自身;停用类型也占名)。

        :raises ServiceWarning: 冲突(→ code 601)
        """
        existing = await DictDao.get_dict_type_by_type_any_status(query_db, dict_type)
        if existing and existing.dict_id != exclude_id:
            raise ServiceWarning(message=f'字典类型「{dict_type}」已存在')

    @classmethod
    async def add_dict_type_services(cls, query_db: AsyncSession, page_object: DictTypeAddModel) -> CrudResponseModel:
        """新增字典类型:唯一性校验 → 落库。"""
        await cls._check_dict_type_unique(query_db, page_object.dict_type)
        try:
            add_type = SysDictType(**page_object.model_dump())
            add_result = await DictDao.add_dict_type_dao(query_db, add_type)
            dict_id, dict_type = add_result.dict_id, add_result.dict_type  # commit 前取值(属性会过期)
            await query_db.commit()
            logger.info(f'[字典] 类型新增成功 dict_type={dict_type} dict_id={dict_id}')
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[字典] 类型新增失败回滚 dict_type={page_object.dict_type} | {e}')
            raise e

    @classmethod
    async def edit_dict_type_services(cls, query_db: AsyncSession, page_object: DictTypeEditModel) -> CrudResponseModel:
        """编辑字典类型:存在性 + 唯一性校验 + 内置类型的权限标识禁改。

        内置保护:种子类型(1/2/3)的 dict_type 是前端 DictTag 消费的接口契约
        (如 sys_normal_disable),改了会让全站状态标签瞬间失效——禁改标识,其余可改。
        """
        dict_id = page_object.dict_id
        dict_type_row = await DictDao.get_dict_type_by_id(query_db, dict_id)
        if dict_type_row is None:
            raise ServiceWarning(message=f'修改字典类型{page_object.dict_name}失败，字典类型不存在')
        if dict_id in SEED_DICT_TYPE_IDS and page_object.dict_type != dict_type_row.dict_type:
            raise ServiceWarning(message='内置字典类型的标识不允许修改')
        await cls._check_dict_type_unique(query_db, page_object.dict_type, dict_id)
        try:
            edit_type = page_object.model_dump(exclude_unset=True)
            # 内置类型禁改标识的兜底:即便前端绕过校验也不落标识变更
            if dict_id in SEED_DICT_TYPE_IDS:
                edit_type['dict_type'] = dict_type_row.dict_type
            await DictDao.edit_dict_type_dao(query_db, edit_type)
            await query_db.commit()
            logger.info(f'[字典] 类型编辑成功 dict_id={dict_id}')
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[字典] 类型编辑失败回滚 dict_id={dict_id} | {e}')
            raise e

    @classmethod
    async def delete_dict_type_services(cls, query_db: AsyncSession, page_object: DeleteDictTypeModel) -> CrudResponseModel:
        """删除字典类型(物理删除,表无 del_flag)。

        校验链:格式 → 种子保护 → 存在性 → 有数据禁删,全部通过才动库。
        """
        if not page_object.dict_ids:
            raise ServiceWarning(message='传入字典ID为空')
        raw_ids = [raw.strip() for raw in page_object.dict_ids.split(',') if raw.strip()]
        try:
            dict_id_list = list(dict.fromkeys(int(raw) for raw in raw_ids))
        except ValueError as e:
            raise ServiceWarning(message='字典ID格式不正确(应为逗号分隔的数字)') from e
        if not dict_id_list:
            raise ServiceWarning(message='传入字典ID为空')
        # 种子保护:内置类型是前端消费契约,禁删
        seed_hit = [str(i) for i in dict_id_list if i in SEED_DICT_TYPE_IDS]
        if seed_hit:
            raise ServiceWarning(message=f'内置字典类型不允许删除(dict_id={",".join(seed_hit)})')
        # 存在性前置校验
        existing_types = await DictDao.get_dict_types_by_ids(query_db, dict_id_list)
        existing_ids = {t.dict_id for t in existing_types}
        missing_ids = [str(i) for i in dict_id_list if i not in existing_ids]
        if missing_ids:
            raise ServiceWarning(message=f'字典类型不存在(dict_id={",".join(missing_ids)})')
        # 有数据禁删(防悬空字典数据,先清数据再删类型)
        for dict_type_row in existing_types:
            data_count = await DictDao.count_data_by_dict_type(query_db, dict_type_row.dict_type)
            if data_count > 0:
                raise ServiceWarning(
                    message=f'字典类型「{dict_type_row.dict_name}」存在{data_count}条字典数据，请先删除数据'
                )
        try:
            type_names = [t.dict_type for t in existing_types]  # commit 前取值(属性会过期)
            await DictDao.delete_dict_types_by_ids(query_db, dict_id_list)
            await query_db.commit()
            logger.info(f'[字典] 类型删除成功 dict_ids={page_object.dict_ids}({type_names})')
            return CrudResponseModel(is_success=True, message='删除成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[字典] 类型删除失败回滚 dict_ids={page_object.dict_ids} | {e}')
            raise e

    # ---------- 管理端:字典数据 ----------

    @classmethod
    async def get_dict_data_list_services(cls, query_db: AsyncSession, dict_type: str) -> list[dict]:
        """获取某类型的全部字典数据(管理端列表,不过滤 status,按 dict_sort 排序)。"""
        dict_type_row = await DictDao.get_dict_type_by_type_any_status(query_db, dict_type)
        if dict_type_row is None:
            raise ServiceWarning(message=f'字典类型「{dict_type}」不存在')
        data_rows = await DictDao.get_dict_data_all_by_type(query_db, dict_type)
        return [CamelCaseUtil.transform_result(row) for row in data_rows]

    @classmethod
    async def get_dict_data_detail_services(cls, query_db: AsyncSession, dict_code: int) -> dict:
        """获取字典数据详情。"""
        dict_data = await DictDao.get_dict_data_by_code(query_db, dict_code)
        if dict_data is None:
            raise ServiceWarning(message='字典数据不存在')
        return CamelCaseUtil.transform_result(dict_data)

    @classmethod
    async def _check_dict_value_unique(
        cls, query_db: AsyncSession, dict_type: str, dict_value: str, exclude_code: int = -1
    ) -> None:
        """同类型内字典键值唯一性校验(编辑时排除自身)。

        :raises ServiceWarning: 冲突(→ code 601)
        """
        existing = await DictDao.get_dict_data_by_type_and_value(query_db, dict_type, dict_value)
        if existing and existing.dict_code != exclude_code:
            raise ServiceWarning(message=f'字典键值「{dict_value}」在该类型下已存在')

    @classmethod
    async def add_dict_data_services(cls, query_db: AsyncSession, page_object: DictDataAddModel) -> CrudResponseModel:
        """新增字典数据:所属类型必须存在 + 类型内键值唯一。"""
        dict_type_row = await DictDao.get_dict_type_by_type_any_status(query_db, page_object.dict_type)
        if dict_type_row is None:
            raise ServiceWarning(message=f'字典类型「{page_object.dict_type}」不存在')
        await cls._check_dict_value_unique(query_db, page_object.dict_type, page_object.dict_value)
        try:
            add_data = SysDictData(**page_object.model_dump())
            add_result = await DictDao.add_dict_data_dao(query_db, add_data)
            dict_code, dict_label = add_result.dict_code, add_result.dict_label  # commit 前取值
            await query_db.commit()
            logger.info(f'[字典] 数据新增成功 dict_code={dict_code} dict_label={dict_label}')
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[字典] 数据新增失败回滚 dict_type={page_object.dict_type} | {e}')
            raise e

    @classmethod
    async def edit_dict_data_services(cls, query_db: AsyncSession, page_object: DictDataEditModel) -> CrudResponseModel:
        """编辑字典数据:存在性 + 所属类型存在 + 键值唯一校验。

        注意:不允许修改所属类型(跨类型迁移易留幽灵数据,需要时删除重建)。
        """
        dict_code = page_object.dict_code
        dict_data = await DictDao.get_dict_data_by_code(query_db, dict_code)
        if dict_data is None:
            raise ServiceWarning(message='编辑字典数据失败，字典数据不存在')
        # 所属类型锁定为原值(前端若传了别的类型直接驳回,避免静默迁移)
        if page_object.dict_type != dict_data.dict_type:
            raise ServiceWarning(message='字典数据不允许修改所属类型')
        await cls._check_dict_value_unique(query_db, page_object.dict_type, page_object.dict_value, dict_code)
        try:
            edit_data = page_object.model_dump(exclude_unset=True)
            await DictDao.edit_dict_data_dao(query_db, edit_data)
            await query_db.commit()
            logger.info(f'[字典] 数据编辑成功 dict_code={dict_code}')
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[字典] 数据编辑失败回滚 dict_code={dict_code} | {e}')
            raise e

    @classmethod
    async def delete_dict_data_services(cls, query_db: AsyncSession, page_object: DeleteDictDataModel) -> CrudResponseModel:
        """删除字典数据(物理删除,表无 del_flag)。

        校验链:格式 → 种子保护 → 存在性,全部通过才动库。
        """
        if not page_object.dict_ids:
            raise ServiceWarning(message='传入字典编码为空')
        raw_ids = [raw.strip() for raw in page_object.dict_ids.split(',') if raw.strip()]
        try:
            code_list = list(dict.fromkeys(int(raw) for raw in raw_ids))
        except ValueError as e:
            raise ServiceWarning(message='字典编码格式不正确(应为逗号分隔的数字)') from e
        if not code_list:
            raise ServiceWarning(message='传入字典编码为空')
        # 种子保护:内置字典项是前端消费契约(如 正常/停用),禁删
        seed_hit = [str(c) for c in code_list if c in SEED_DICT_DATA_CODES]
        if seed_hit:
            raise ServiceWarning(message=f'内置字典数据不允许删除(dict_code={",".join(seed_hit)})')
        # 存在性前置校验
        existing_data = await DictDao.get_dict_data_by_codes(query_db, code_list)
        existing_codes = {d.dict_code for d in existing_data}
        missing_codes = [str(c) for c in code_list if c not in existing_codes]
        if missing_codes:
            raise ServiceWarning(message=f'字典数据不存在(dict_code={",".join(missing_codes)})')
        try:
            labels = [d.dict_label for d in existing_data]  # commit 前取值(属性会过期)
            await DictDao.delete_dict_data_by_codes(query_db, code_list)
            await query_db.commit()
            logger.info(f'[字典] 数据删除成功 dict_codes={page_object.dict_ids}({labels})')
            return CrudResponseModel(is_success=True, message='删除成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[字典] 数据删除失败回滚 dict_codes={page_object.dict_ids} | {e}')
            raise e
