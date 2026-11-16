"""基金管理模块 Service(业务逻辑层):基金详细信息。

三级缓存链路照 AkshareService.get_fund_nav 范式:
Redis(fund_info:{code}, TTL 1 小时) → 数据库 fund_info 表 → akshare fund_info_ths 回源。
"""

import asyncio
import json
from typing import Any

import akshare as ak
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from common.enums import RedisInitKeyConfig
from common.response import PageModel
from exceptions.exceptions import ServiceWarning
from module_fund.dao.fund_info_dao import FundInfoDao
from utils.log import logger

# 详情是低频变化档案数据(成立规模/份额按季更新),固定 1 小时即可,不适用净值的窗口对齐 TTL
FUND_INFO_TTL = 3600


def _cache_key(fund_code: str) -> str:
    return f'{RedisInitKeyConfig.FUND_INFO.key}:{fund_code}'


async def _cache_get(redis: aioredis.Redis, key: str) -> Any:
    """读 Redis JSON 缓存,未命中返回 None。"""
    cached = await redis.get(key)
    return json.loads(cached) if cached else None


async def _cache_set(redis: aioredis.Redis, key: str, value: Any, ttl: int) -> None:
    """写 Redis JSON 缓存(带 TTL)。"""
    await redis.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)


def _fetch_fund_info_from_ths(symbol: str) -> dict[str, str]:
    """拉取同花顺基金档案(同步阻塞,调用侧需 to_thread)。

    返回「字段 → 值」dict;值统一转字符串(源站值类型混杂,前端展示直接可用)。
    """
    df = ak.fund_info_ths(symbol=symbol)
    if df is None or df.empty:
        raise ValueError(f'同花顺未返回基金 {symbol} 的档案信息')
    return dict(zip(df['字段'], df['值'].astype(str)))


class FundInfoService:
    """基金详细信息服务(三级缓存编排)。"""

    @classmethod
    async def get_fund_info_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str
    ) -> dict[str, str]:
        """获取基金详细信息(Redis → DB → akshare 回源)。

        回源失败即 601(此时 DB 必无记录——DB 命中就不会走到回源,无旧值可降级)。
        """
        key = _cache_key(fund_code)

        # ① Redis
        cached = await _cache_get(redis, key)
        if cached is not None:
            return cached

        # ② 数据库(命中后回写 Redis,让后续请求吃缓存)
        record = await FundInfoDao.get_info_by_code(query_db, fund_code)
        if record:
            info: dict[str, str] = record.info
            await _cache_set(redis, key, info, FUND_INFO_TTL)
            return info

        # ③ akshare 回源(fund_info_ths 为同步阻塞,to_thread 避免占死事件循环)
        try:
            info = await asyncio.to_thread(_fetch_fund_info_from_ths, fund_code)
        except Exception as e:
            logger.warning(f'[基金详情] akshare 回源失败 fund_code={fund_code} | {e}')
            raise ServiceWarning(message=f'无法获取基金 {fund_code} 的详细信息，请稍后再试')

        try:
            await FundInfoDao.upsert_info(query_db, fund_code, info)
            await query_db.commit()
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[基金详情] 详情落库失败回滚 fund_code={fund_code} | {e}')
            raise e

        await _cache_set(redis, key, info, FUND_INFO_TTL)
        logger.info(f'[基金详情] 回源成功 fund_code={fund_code} fields={len(info)}')
        return info

    # ==================== 管理端(历史持仓缓存的管理入口,2026-10-12) ====================

    @classmethod
    async def get_info_page_services(
        cls,
        query_db: AsyncSession,
        page_num: int,
        page_size: int,
        keyword: str | None = None,
    ) -> PageModel:
        """分页列表(窄投影,不含 info 大 JSON);详情由前端按 code 单查。"""
        return await FundInfoDao.get_info_page(
            query_db, page_num, page_size, keyword
        )

    @classmethod
    async def refresh_info_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str
    ) -> dict[str, str]:
        """强制回源刷新单只基金档案(绕过 Redis 与 DB,直拉同花顺)。

        这是本页存在的意义:三级缓存里 DB 命中后不再回源,档案数据会停在
        首次抓取的快照——管理页的「同步/新增」都走这里强制刷新。
        """
        try:
            info = await asyncio.to_thread(_fetch_fund_info_from_ths, fund_code)
        except Exception as e:
            logger.warning(
                f'[基金详情] 强制回源失败 fund_code={fund_code} | {e}'
            )
            raise ServiceWarning(
                message=f'无法获取基金 {fund_code} 的详细信息，请稍后再试'
            )
        try:
            await FundInfoDao.upsert_info(query_db, fund_code, info)
            await query_db.commit()
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[基金详情] 强制回源落库失败回滚 fund_code={fund_code} | {e}')
            raise e
        await _cache_set(redis, _cache_key(fund_code), info, FUND_INFO_TTL)
        logger.info(
            f'[基金详情] 强制回源成功 fund_code={fund_code} fields={len(info)}'
        )
        return info

    @classmethod
    async def sync_all_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis
    ) -> dict:
        """全量同步:遍历表内全部基金逐个强制回源刷新。

        逐只独立提交——单只失败只记清单,不拖垮整批;返回成功/失败统计。
        **必须节流**(2026-10-13 实证):逐只无间隔连拉约 10 只后被同花顺
        限流,其后全部报"未找到基金信息"(直测单只全部正常,证明不是
        源站缺档案)——故只间 sleep 0.6s,失败冷却 2s 重试一次。
        回源是逐只同步阻塞调用(to_thread),几十只基金耗时数十秒,
        调用侧必须给充足的请求超时。
        """
        codes = await FundInfoDao.get_all_codes(query_db)
        ok, failed = 0, []
        for idx, code in enumerate(codes):
            if idx > 0:
                await asyncio.sleep(0.6)
            try:
                await cls.refresh_info_services(query_db, redis, code)
                ok += 1
            except Exception:
                # 疑似限流:冷却后重试一次,仍失败才计入清单
                await asyncio.sleep(2)
                try:
                    await cls.refresh_info_services(query_db, redis, code)
                    ok += 1
                    logger.info(f'[基金详情] 全量同步重试成功 code={code}')
                except Exception as e:
                    failed.append(f'{code}')
                    logger.warning(f'[基金详情] 全量同步单只失败 code={code} | {e}')
        logger.info(
            f'[基金详情] 全量同步完成 成功={ok} 失败={len(failed)} 清单={failed}'
        )
        return {'total': len(codes), 'success': ok, 'failedCodes': failed}

    @classmethod
    async def create_info_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str
    ) -> dict[str, str]:
        """手动新增:按代码回源抓取档案入库;已存在则提示走同步。"""
        existing = await FundInfoDao.get_info_by_code(query_db, fund_code)
        if existing:
            raise ServiceWarning(message=f'基金 {fund_code} 的详细信息已存在，请使用同步更新')
        return await cls.refresh_info_services(query_db, redis, fund_code)

    @classmethod
    async def delete_info_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str
    ) -> None:
        """删除缓存行并清 Redis(删除后详情接口会重新回源,可随时恢复)。"""
        removed = await FundInfoDao.delete_by_code(query_db, fund_code)
        if not removed:
            raise ServiceWarning(message=f'基金 {fund_code} 的详细信息不存在')
        await query_db.commit()
        await redis.delete(_cache_key(fund_code))
        logger.info(f'[基金详情] 删除缓存行 fund_code={fund_code}')
