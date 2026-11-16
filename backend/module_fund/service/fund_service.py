"""基金管理模块 Service(业务逻辑层)。

职责:基金 CRUD 编排(唯一性/引用校验)+ AkShare 同步落库 + 事务控制。
"""

from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from common.response import CrudResponseModel, PageModel
from exceptions.exceptions import ServiceWarning
from module_fund.dao.fund_dao import FundDao
from module_fund.dao.fund_nav_dao import FundNavDao
from module_fund.entity.do.fund_do import Fund
from module_fund.entity.vo.fund_vo import (
    DeleteFundModel,
    FundAddModel,
    FundEditModel,
    FundNavQueryModel,
    FundPageQueryModel,
)
from module_fund.service.akshare_service import AkshareService
from module_portfolio.dao.position_dao import PositionDao
from utils.camel_case_util import CamelCaseUtil
from utils.log import logger


class FundService:
    """基金管理模块服务层。"""

    # ---------- 查询 ----------

    @classmethod
    async def get_fund_list_services(
        cls, query_db: AsyncSession, query_object: FundPageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict]:
        """获取基金分页列表。"""
        return await FundDao.get_fund_list(query_db, query_object, is_page)

    @classmethod
    async def get_fund_detail_services(cls, query_db: AsyncSession, fund_id: int) -> dict:
        """获取基金详情。"""
        fund = await FundDao.get_fund_by_id(query_db, fund_id)
        if fund is None:
            raise ServiceWarning(message='基金不存在')
        return CamelCaseUtil.transform_result(fund)

    @classmethod
    async def get_fund_by_code_services(cls, query_db: AsyncSession, code: str) -> Fund | None:
        """按基金代码获取未删除基金(跨模块业务定位用)。"""
        return await FundDao.get_fund_by_code(query_db, code)

    # ---------- 写操作 ----------

    @classmethod
    async def add_fund_services(cls, query_db: AsyncSession, page_object: FundAddModel) -> CrudResponseModel:
        """新增基金:代码唯一性前置校验(含已删记录,防唯一约束裸炸)→ 落库。"""
        exist = await FundDao.get_any_fund_by_code(query_db, page_object.code)
        if exist:
            raise ServiceWarning(message=f'基金代码「{page_object.code}」已存在')
        try:
            add_fund = Fund(**page_object.model_dump(exclude={'fund_id'}))
            await FundDao.add_fund_dao(query_db, add_fund)
            await query_db.commit()
            logger.info(f'[基金] 新增成功 code={page_object.code} name={page_object.name}')
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[基金] 新增失败回滚 code={page_object.code} | {e}')
            raise e

    @classmethod
    async def edit_fund_services(cls, query_db: AsyncSession, page_object: FundEditModel) -> CrudResponseModel:
        """编辑基金:存在性 + 唯一性(排除自身)校验 → 更新。"""
        fund = await FundDao.get_fund_by_id(query_db, page_object.fund_id)
        if fund is None:
            raise ServiceWarning(message=f'修改基金{page_object.name}失败，基金不存在')
        same_code = await FundDao.get_any_fund_by_code(query_db, page_object.code)
        if same_code and same_code.fund_id != page_object.fund_id:
            raise ServiceWarning(message=f'基金代码「{page_object.code}」已存在')
        try:
            edit_fund = page_object.model_dump(exclude_unset=True)
            await FundDao.edit_fund_dao(query_db, edit_fund)
            await query_db.commit()
            logger.info(f'[基金] 编辑成功 fund_id={page_object.fund_id}')
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[基金] 编辑失败回滚 fund_id={page_object.fund_id} | {e}')
            raise e

    @classmethod
    async def delete_fund_services(cls, query_db: AsyncSession, page_object: DeleteFundModel) -> CrudResponseModel:
        """删除基金(逻辑删除):引用检查(持仓引用即拒删,含已删持仓——历史交易仍需基金信息)。"""
        if not page_object.fund_ids:
            raise ServiceWarning(message='传入基金ID为空')
        fund_id_list = page_object.fund_ids.split(',')
        # 前置校验全部通过才动库(避免半删状态)
        for fund_id in fund_id_list:
            fund = await FundDao.get_fund_by_id(query_db, int(fund_id))
            if fund is None:
                raise ServiceWarning(message=f'基金不存在(fund_id={fund_id})')
            position_count = await PositionDao.count_positions_by_fund_code(query_db, fund.code)
            if position_count > 0:
                raise ServiceWarning(message=f'基金「{fund.name}」已被持仓引用，无法删除')
        try:
            for fund_id in fund_id_list:
                await FundDao.delete_fund_dao(query_db, int(fund_id), page_object.update_by, page_object.update_time)
            await query_db.commit()
            logger.info(f'[基金] 删除成功 fund_ids={page_object.fund_ids}')
            return CrudResponseModel(is_success=True, message='删除成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[基金] 删除失败回滚 fund_ids={page_object.fund_ids} | {e}')
            raise e

    @classmethod
    async def get_fund_types_services(cls, query_db: AsyncSession) -> list[str]:
        """获取库内现有基金类型(纯透传,保持 Controller 不直接碰 DAO 的分层纪律)。"""
        return await FundDao.get_fund_types(query_db)

    @classmethod
    async def get_nav_page_services(cls, query_db: AsyncSession, query_object: FundNavQueryModel) -> PageModel:
        """基金净值分页列表(纯透传,保持 Controller 不直接碰 DAO 的分层纪律)。"""
        return await FundNavDao.get_nav_page(query_db, query_object)

    # ---------- 同步 ----------

    @classmethod
    async def sync_funds_services(cls, query_db: AsyncSession) -> int:
        """从 AkShare 全量同步基金基础信息(已存在的代码跳过),返回新增数量。"""
        funds_data = await AkshareService.get_all_funds_from_akshare()
        if not funds_data:
            raise ServiceWarning(message='未从 AkShare 获取到基金数据')
        count = 0
        try:
            for fund_data in funds_data:
                existing = await FundDao.get_any_fund_by_code(query_db, fund_data['code'])
                if not existing:
                    await FundDao.add_fund_dao(query_db, Fund(**fund_data))
                    count += 1
            await query_db.commit()
            logger.info(f'[基金] 全量同步完成 新增={count} 获取={len(funds_data)}')
            return count
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[基金] 全量同步失败回滚 | {e}')
            raise e

    @classmethod
    async def sync_fund_nav_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str
    ) -> list[dict]:
        """同步单只基金净值(三级缓存未命中时拉取 Eastmoney 并回写)。"""
        records = await AkshareService.get_fund_nav(query_db, redis, fund_code)
        logger.info(f'[基金] 净值同步完成 fund_code={fund_code} records={len(records)}')
        return records
