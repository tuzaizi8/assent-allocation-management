"""资产配置模块 Service(业务逻辑层)。

职责:资产类别/配置模式/目标占比/基金映射四组 CRUD 编排
+ set-default 互斥 + 当前持仓占比与目标占比的对比分析。
"""

from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from common.response import CrudResponseModel
from exceptions.exceptions import ServiceWarning
from module_asset.dao.asset_class_dao import AssetClassDao
from module_asset.dao.asset_class_mode_dao import AssetClassModeDao
from module_asset.dao.asset_class_target_dao import AssetClassTargetDao
from module_asset.dao.fund_mapping_dao import FundMappingDao
from module_asset.entity.do.asset_class_do import (
    AssetClass,
    AssetClassMode,
    AssetClassTarget,
    FundAssetMapping,
)
from module_asset.entity.vo.asset_vo import (
    AssetClassAddModel,
    AssetClassEditModel,
    AssetClassModeAddModel,
    AssetClassModeEditModel,
    AssetClassTargetBatchModel,
    FundMappingModel,
)
from module_fund.dao.fund_dao import FundDao
from module_fund.service.akshare_service import AkshareService
from module_portfolio.dao.position_dao import PositionDao
from module_portfolio.dao.purchase_record_dao import PurchaseRecordDao
from module_portfolio.dao.redemption_record_dao import RedemptionRecordDao
from module_portfolio.service.position_calc_util import remaining_shares
from utils.camel_case_util import CamelCaseUtil
from utils.log import logger


class AssetAllocationService:
    """资产配置服务层。"""

    # ==================== 资产类别 ====================

    @classmethod
    async def get_asset_classes_services(cls, query_db: AsyncSession, user_id: int) -> list[dict]:
        """获取用户全部资产类别。"""
        classes = await AssetClassDao.get_asset_classes(query_db, user_id)
        return [CamelCaseUtil.transform_result(c) for c in classes]

    @classmethod
    async def add_asset_class_services(
        cls, query_db: AsyncSession, user_id: int, page_object: AssetClassAddModel
    ) -> CrudResponseModel:
        """新增资产类别。"""
        try:
            await AssetClassDao.add_asset_class_dao(
                query_db, AssetClass(user_id=user_id, **page_object.model_dump())
            )
            await query_db.commit()
            logger.info(f'[资产类别] 新增成功 user_id={user_id} name={page_object.name}')
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[资产类别] 新增失败回滚 user_id={user_id} | {e}')
            raise e

    @classmethod
    async def edit_asset_class_services(
        cls, query_db: AsyncSession, user_id: int, page_object: AssetClassEditModel
    ) -> CrudResponseModel:
        """编辑资产类别。"""
        asset_class = await AssetClassDao.get_asset_class_by_id(query_db, page_object.asset_class_id, user_id)
        if asset_class is None:
            raise ServiceWarning(message=f'修改资产类别{page_object.name}失败，资产类别不存在')
        try:
            for key, value in page_object.model_dump(exclude={'asset_class_id'}, exclude_unset=True).items():
                if value is not None:
                    setattr(asset_class, key, value)
            await query_db.commit()
            logger.info(f'[资产类别] 编辑成功 asset_class_id={page_object.asset_class_id}')
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[资产类别] 编辑失败回滚 asset_class_id={page_object.asset_class_id} | {e}')
            raise e

    @classmethod
    async def delete_asset_class_services(
        cls, query_db: AsyncSession, user_id: int, asset_class_id: int
    ) -> CrudResponseModel:
        """删除资产类别:映射引用即拒删;目标占比为类别自有配置,级联清理。"""
        asset_class = await AssetClassDao.get_asset_class_by_id(query_db, asset_class_id, user_id)
        if asset_class is None:
            raise ServiceWarning(message='资产类别不存在')
        mapping_count = await FundMappingDao.count_mappings_by_asset_class(query_db, asset_class_id)
        if mapping_count > 0:
            raise ServiceWarning(message=f'资产类别「{asset_class.name}」已被 {mapping_count} 只基金映射，请先解除映射')
        try:
            await AssetClassTargetDao.delete_targets_by_asset_class(query_db, asset_class_id)
            await AssetClassDao.delete_asset_class_dao(query_db, asset_class_id)
            await query_db.commit()
            logger.info(f'[资产类别] 删除成功 asset_class_id={asset_class_id}')
            return CrudResponseModel(is_success=True, message='删除成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[资产类别] 删除失败回滚 asset_class_id={asset_class_id} | {e}')
            raise e

    # ==================== 配置模式 ====================

    @classmethod
    async def get_modes_services(cls, query_db: AsyncSession, user_id: int) -> list[dict]:
        """获取用户全部配置模式。"""
        modes = await AssetClassModeDao.get_modes(query_db, user_id)
        return [CamelCaseUtil.transform_result(m) for m in modes]

    @classmethod
    async def add_mode_services(
        cls, query_db: AsyncSession, user_id: int, page_object: AssetClassModeAddModel
    ) -> CrudResponseModel:
        """新增配置模式(设为默认时互斥清位)。"""
        try:
            if page_object.is_default:
                await AssetClassModeDao.clear_default_for_user(query_db, user_id)
            await AssetClassModeDao.add_mode_dao(
                query_db, AssetClassMode(user_id=user_id, **page_object.model_dump())
            )
            await query_db.commit()
            logger.info(f'[配置模式] 新增成功 user_id={user_id} name={page_object.name}')
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[配置模式] 新增失败回滚 user_id={user_id} | {e}')
            raise e

    @classmethod
    async def edit_mode_services(
        cls, query_db: AsyncSession, user_id: int, page_object: AssetClassModeEditModel
    ) -> CrudResponseModel:
        """编辑配置模式(改为默认时互斥清位)。"""
        mode = await AssetClassModeDao.get_mode_by_id(query_db, page_object.mode_id, user_id)
        if mode is None:
            raise ServiceWarning(message=f'修改配置模式{page_object.name}失败，配置模式不存在')
        try:
            if page_object.is_default:
                await AssetClassModeDao.clear_default_for_user(query_db, user_id)
            for key, value in page_object.model_dump(exclude={'mode_id'}, exclude_unset=True).items():
                if value is not None:
                    setattr(mode, key, value)
            await query_db.commit()
            logger.info(f'[配置模式] 编辑成功 mode_id={page_object.mode_id}')
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[配置模式] 编辑失败回滚 mode_id={page_object.mode_id} | {e}')
            raise e

    @classmethod
    async def delete_mode_services(cls, query_db: AsyncSession, user_id: int, mode_id: int) -> CrudResponseModel:
        """删除配置模式(级联清理目标占比)。"""
        mode = await AssetClassModeDao.get_mode_by_id(query_db, mode_id, user_id)
        if mode is None:
            raise ServiceWarning(message='配置模式不存在')
        try:
            await AssetClassTargetDao.delete_targets_by_mode(query_db, mode_id)
            await AssetClassModeDao.delete_mode_dao(query_db, mode_id)
            await query_db.commit()
            logger.info(f'[配置模式] 删除成功 mode_id={mode_id}')
            return CrudResponseModel(is_success=True, message='删除成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[配置模式] 删除失败回滚 mode_id={mode_id} | {e}')
            raise e

    @classmethod
    async def set_default_mode_services(cls, query_db: AsyncSession, user_id: int, mode_id: int) -> CrudResponseModel:
        """设置默认模式(同用户互斥)。"""
        mode = await AssetClassModeDao.get_mode_by_id(query_db, mode_id, user_id)
        if mode is None:
            raise ServiceWarning(message='配置模式不存在')
        try:
            await AssetClassModeDao.clear_default_for_user(query_db, user_id)
            mode.is_default = True
            await query_db.commit()
            logger.info(f'[配置模式] 设为默认 mode_id={mode_id} user_id={user_id}')
            return CrudResponseModel(is_success=True, message='设置成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[配置模式] 设默认失败回滚 mode_id={mode_id} | {e}')
            raise e

    # ==================== 目标占比 ====================

    @classmethod
    async def get_mode_targets_services(cls, query_db: AsyncSession, user_id: int, mode_id: int) -> dict:
        """获取指定模式下的全部目标占比(含资产类别名称/颜色与合计)。"""
        mode = await AssetClassModeDao.get_mode_by_id(query_db, mode_id, user_id)
        if mode is None:
            raise ServiceWarning(message='配置模式不存在')

        targets = await AssetClassTargetDao.get_targets_by_mode(query_db, mode_id)
        asset_classes = await AssetClassDao.get_asset_classes(query_db, user_id)
        asset_class_map = {ac.asset_class_id: ac for ac in asset_classes}

        target_list = []
        total_ratio = 0.0
        for t in targets:
            ac = asset_class_map.get(t.asset_class_id)
            target_list.append({
                'targetId': t.target_id,
                'modeId': t.mode_id,
                'assetClassId': t.asset_class_id,
                'assetClassName': ac.name if ac else str(t.asset_class_id),
                'assetClassColor': ac.color if ac else None,
                'targetRatio': float(t.target_ratio),
            })
            total_ratio += float(t.target_ratio)

        return {
            'modeId': mode.mode_id,
            'modeName': mode.name,
            'isDefault': mode.is_default,
            'targets': target_list,
            'totalRatio': round(total_ratio, 2),
        }

    @classmethod
    async def update_mode_targets_services(
        cls, query_db: AsyncSession, user_id: int, mode_id: int, page_object: AssetClassTargetBatchModel
    ) -> dict:
        """批量更新目标占比(全量替换:先删后插,对齐角色-菜单绑定范式)。"""
        mode = await AssetClassModeDao.get_mode_by_id(query_db, mode_id, user_id)
        if mode is None:
            raise ServiceWarning(message='配置模式不存在')
        # 占比全集校验(目标总和应为 100,容差 0.01)
        total = sum(t.target_ratio for t in page_object.targets)
        if abs(total - 100) > 0.01:
            raise ServiceWarning(message=f'目标占比合计应为 100%，当前为 {total:.2f}%')
        try:
            await AssetClassTargetDao.delete_targets_by_mode(query_db, mode_id)
            for t in page_object.targets:
                await AssetClassTargetDao.add_target_dao(
                    query_db,
                    AssetClassTarget(mode_id=mode_id, asset_class_id=t.asset_class_id, target_ratio=t.target_ratio),
                )
            await query_db.commit()
            logger.info(f'[目标占比] 全量替换完成 mode_id={mode_id} 条数={len(page_object.targets)}')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[目标占比] 更新失败回滚 mode_id={mode_id} | {e}')
            raise e
        return await cls.get_mode_targets_services(query_db, user_id, mode_id)

    # ==================== 基金映射 ====================

    @classmethod
    async def get_fund_mappings_services(cls, query_db: AsyncSession, user_id: int) -> list[dict]:
        """获取用户全部基金映射(装配基金与类别信息)。"""
        mappings = await FundMappingDao.get_fund_mappings(query_db, user_id)
        asset_classes = await AssetClassDao.get_asset_classes(query_db, user_id)
        asset_class_map = {ac.asset_class_id: ac for ac in asset_classes}

        responses = []
        for m in mappings:
            fund = await FundDao.get_fund_by_id(query_db, m.fund_id)
            ac = asset_class_map.get(m.asset_class_id)
            responses.append({
                'mappingId': m.mapping_id,
                'userId': m.user_id,
                'fundId': m.fund_id,
                'fundCode': fund.code if fund else str(m.fund_id),
                'fundName': fund.name if fund else '未知基金',
                'assetClassId': m.asset_class_id,
                'assetClassName': ac.name if ac else '未知类别',
                'assetClassColor': ac.color if ac else None,
            })
        return responses

    @classmethod
    async def map_fund_to_class_services(
        cls, query_db: AsyncSession, user_id: int, page_object: FundMappingModel
    ) -> CrudResponseModel:
        """创建或更新基金映射(基金与类别归属校验)。"""
        fund = await FundDao.get_fund_by_id(query_db, page_object.fund_id)
        if fund is None:
            raise ServiceWarning(message='基金不存在')
        asset_class = await AssetClassDao.get_asset_class_by_id(query_db, page_object.asset_class_id, user_id)
        if asset_class is None:
            raise ServiceWarning(message='资产类别不存在')
        # 会话工厂已设 expire_on_commit=False:落局部变量不是为了防 MissingGreenlet,
        # 而是让后续逻辑不内嵌 ORM 对象
        fund_code = fund.code
        try:
            existing = await FundMappingDao.get_mapping_by_fund(query_db, user_id, page_object.fund_id)
            if existing:
                existing.asset_class_id = page_object.asset_class_id
            else:
                await FundMappingDao.add_mapping_dao(
                    query_db,
                    FundAssetMapping(
                        user_id=user_id,
                        fund_id=page_object.fund_id,
                        asset_class_id=page_object.asset_class_id,
                    ),
                )
            await query_db.commit()
            logger.info(f'[基金映射] 保存成功 user_id={user_id} fund_code={fund_code}')
            return CrudResponseModel(is_success=True, message='保存成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[基金映射] 保存失败回滚 user_id={user_id} fund_id={page_object.fund_id} | {e}')
            raise e

    @classmethod
    async def delete_fund_mapping_services(
        cls, query_db: AsyncSession, user_id: int, fund_id: int
    ) -> CrudResponseModel:
        """删除基金映射。"""
        deleted = await FundMappingDao.delete_mapping_by_fund(query_db, user_id, fund_id)
        if deleted == 0:
            raise ServiceWarning(message='基金映射不存在')
        await query_db.commit()
        logger.info(f'[基金映射] 删除成功 user_id={user_id} fund_id={fund_id}')
        return CrudResponseModel(is_success=True, message='删除成功')

    @classmethod
    async def get_unmapped_funds_services(cls, query_db: AsyncSession, user_id: int) -> list[dict]:
        """获取持仓中未映射的基金。"""
        funds = await FundMappingDao.get_unmapped_funds(query_db, user_id)
        return [
            {
                'fundId': f.fund_id,
                'fundCode': f.code,
                'fundName': f.name,
                'fundType': f.fund_type,
            }
            for f in funds
        ]

    # ==================== 配置对比 ====================

    @classmethod
    async def compare_allocation_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, mode_id: int
    ) -> dict:
        """获取当前持仓占比 vs 目标占比对比(超配/低配/达标)。"""
        mode = await AssetClassModeDao.get_mode_by_id(query_db, mode_id, user_id)
        if mode is None:
            raise ServiceWarning(message='配置模式不存在')

        mode_targets = await cls.get_mode_targets_services(query_db, user_id, mode_id)
        target_map = {t['assetClassId']: t['targetRatio'] for t in mode_targets['targets']}
        asset_classes = await AssetClassDao.get_asset_classes(query_db, user_id)
        asset_class_map = {ac.asset_class_id: ac for ac in asset_classes}

        positions = await PositionDao.get_positions(query_db, user_id)

        class_values: dict[int, float] = {}
        total_value = 0.0
        unmapped_value = 0.0

        for pos in positions:
            fund = await FundDao.get_fund_by_code(query_db, pos.fund_code)
            if not fund:
                continue
            purchases = await PurchaseRecordDao.get_purchase_records(query_db, pos.position_id)
            redemptions = await RedemptionRecordDao.get_redemption_records(query_db, pos.position_id)
            shares_now = remaining_shares(purchases, redemptions)
            if shares_now <= 0:
                continue
            nav_records = await AkshareService.get_fund_nav(query_db, redis, fund.code)
            if not nav_records:
                continue
            current_nav = nav_records[-1].get('unit_nav', 0)
            market_value = shares_now * current_nav
            total_value += market_value

            mapping = await FundMappingDao.get_mapping_by_fund(query_db, user_id, fund.fund_id)
            if mapping:
                class_values[mapping.asset_class_id] = class_values.get(mapping.asset_class_id, 0) + market_value
            else:
                unmapped_value += market_value

        items = []
        for ac_id, target_ratio in target_map.items():
            actual_value = class_values.get(ac_id, 0)
            actual_ratio = (actual_value / total_value * 100) if total_value > 0 else 0
            difference = actual_ratio - target_ratio
            ac = asset_class_map.get(ac_id)
            status = '达标' if abs(difference) < 1 else ('超配' if difference > 0 else '低配')
            items.append({
                'assetClassId': ac_id,
                'assetClassName': ac.name if ac else str(ac_id),
                'assetClassColor': ac.color if ac else None,
                'targetRatio': target_ratio,
                'actualRatio': round(actual_ratio, 2),
                'difference': round(difference, 2),
                'status': status,
            })

        unmapped_ratio = (unmapped_value / total_value * 100) if total_value > 0 else 0

        return {
            'modeId': mode.mode_id,
            'modeName': mode.name,
            'modeIsDefault': mode.is_default,
            'totalTarget': round(sum(target_map.values()), 2),
            'totalActual': round(100.0 - unmapped_ratio, 2),
            'items': items,
            'unmappedValue': round(unmapped_value, 2),
            'unmappedRatio': round(unmapped_ratio, 2),
            'totalValue': round(total_value, 2),
        }
