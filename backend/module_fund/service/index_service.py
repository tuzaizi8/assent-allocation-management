"""指数收益率管理 Service(业务逻辑层)。

以 BENCHMARK_INDICES 内置指数为全集,对 index_nav_history 缓存行做查看/强制同步/删除。
无接口权限(仅登录)——指数行情是公共数据,与 /fund/chart/* 一致。
"""

import asyncio
from datetime import datetime

from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.exceptions import ServiceWarning
from module_fund.dao.index_nav_dao import IndexNavDao
from module_fund.entity.do.index_nav_do import IndexNavHistory
from module_fund.service.akshare_service import (
    BENCHMARK_INDICES,
    AkshareService,
    fetch_index_history,
)
from module_fund.service.chart_service import CHART_PERIODS, ChartService
from utils.log import logger

# 代码 → 名称 反查表(同步/删除按 code 走,缓存键与文案按名称走)
_NAME_BY_CODE = {symbol: name for name, symbol in BENCHMARK_INDICES.items()}

# 详情页返回的最近交易日条数
RECENT_LIMIT = 10


class IndexService:
    """指数收益率管理服务(内置指数清单 + 行情缓存管理)。"""

    # ---------- 查询 ----------

    @classmethod
    async def list_indices_services(
        cls,
        query_db: AsyncSession,
        keyword: str | None = None,
        sync_status: str | None = None,
    ) -> list[dict]:
        """内置指数全集 + 库中缓存汇总(集合固定 5 条,不分页)。

        未同步的指数也列出(synced=False、记录数 0),页面打开即有内容。
        """
        rows = await IndexNavDao.list_all(query_db)
        rows_by_code = {row.index_code: row for row in rows}

        items: list[dict] = []
        for name, symbol in BENCHMARK_INDICES.items():
            row = rows_by_code.get(symbol)
            records = cls._records_of(row)
            latest = records[-1] if records else None
            items.append({
                'indexCode': symbol,
                'indexName': name,
                'syncStatus': cls._sync_status_of(row),
                'latestClose': latest.get('close') if latest else None,
                'dailyYield': latest.get('daily_yield') if latest else None,
                'latestDate': latest.get('nav_date') if latest else None,
                'recordCount': len(records) if records else 0,
                'source': (row.nav_data or {}).get('source') if row else None,
                'updateTime': cls._fmt_time(row.update_time) if row else None,
            })

        # 过滤在服务端做(前端把 keyword/syncStatus 放 queryKey,语义清晰);
        # 数据量固定 5 条,这里的过滤纯内存
        if keyword:
            kw = keyword.strip().lower()
            items = [
                item for item in items
                if kw in item['indexName'].lower() or kw in item['indexCode'].lower()
            ]
        if sync_status:
            items = [item for item in items if item['syncStatus'] == sync_status]
        return items

    @classmethod
    async def get_index_detail_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, index_code: str
    ) -> dict:
        """指数详情:元数据 + 区间收益率 + 最近 10 个交易日。

        未同步的指数允许查看(只回元数据,收益率与明细为空)——与列表的「未同步」状态对齐。
        """
        name = cls._name_of(index_code)
        row = await IndexNavDao.get_by_code(query_db, index_code)
        records = cls._records_of(row)
        latest = records[-1] if records else None

        yields: list[dict] = []
        # 档位与图表接口同源(原为本地 5 档子集,漏 6月/5年 两档)
        for period in CHART_PERIODS:
            segment = ChartService.filter_records_by_period(records, period)
            if segment and segment[0].get('close') and segment[-1].get('close'):
                # 与图表接口同口径:区间首日收盘为基准,(末日/首日 - 1) * 100
                pct = round((segment[-1]['close'] / segment[0]['close'] - 1) * 100, 2)
                yields.append({'period': period, 'yieldPct': pct})
            else:
                yields.append({'period': period, 'yieldPct': None})

        meta = {
            'indexCode': index_code,
            'indexName': name,
            'syncStatus': cls._sync_status_of(row),
            'latestClose': latest.get('close') if latest else None,
            'dailyYield': latest.get('daily_yield') if latest else None,
            'latestDate': latest.get('nav_date') if latest else None,
            'recordCount': len(records) if records else 0,
            'source': (row.nav_data or {}).get('source') if row else None,
            'updateTime': cls._fmt_time(row.update_time) if row else None,
        }
        recent = [
            {
                'navDate': record.get('nav_date'),
                'close': record.get('close'),
                'dailyYield': record.get('daily_yield', 0),
            }
            for record in records[-RECENT_LIMIT:]
        ]
        return {**meta, 'yields': yields, 'recent': recent}

    # ---------- 同步(强制回源) ----------

    @classmethod
    async def sync_one_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, index_code: str
    ) -> dict:
        """强制回源同步单个指数(绕过三级缓存新鲜度判定——点同步就是要刷新)。"""
        name = cls._name_of(index_code)
        records = await asyncio.to_thread(fetch_index_history, index_code)
        if not records:
            raise ServiceWarning(message=f'指数「{name}」未从 AkShare 获取到行情数据')
        await IndexNavDao.upsert_nav_history(query_db, index_code, name, records)
        await query_db.commit()
        try:
            await AkshareService.refresh_index_cache(redis, name, records)
        except Exception as cache_err:
            # 缓存回填失败不应让已成功的同步报错:DB 是真相源,旧缓存最多再活一个 TTL
            logger.warning(f'[指数行情] Redis 回填失败 name={name} | {cache_err}')
        logger.info(f'[指数行情] 同步完成 name={name} symbol={index_code} records={len(records)}')
        return {'indexCode': index_code, 'indexName': name, 'recordCount': len(records)}

    @classmethod
    async def sync_all_services(cls, query_db: AsyncSession, redis: aioredis.Redis) -> dict:
        """同步全部内置指数。

        事务粒度:每个指数独立提交——这里是互不相关的独立缓存刷新,
        单指数失败不应拖垮其余(与基金同步的"统一 commit"语义不同,那边是批量新增)。
        """
        success = 0
        failed: list[str] = []
        details: list[dict] = []
        for name, symbol in BENCHMARK_INDICES.items():
            try:
                info = await cls.sync_one_services(query_db, redis, symbol)
                success += 1
                details.append(info)
            except Exception as e:
                # 单指数失败只记清单,不中断整轮同步
                await query_db.rollback()
                failed.append(name)
                logger.error(f'[指数行情] 同步失败 name={name} symbol={symbol} | {e}')
        logger.info(f'[指数行情] 全量同步完成 成功={success} 失败={len(failed)} {failed or ""}')
        return {'success': success, 'failed': failed, 'total': len(BENCHMARK_INDICES), 'details': details}

    # ---------- 删除(清缓存) ----------

    @classmethod
    async def delete_indices_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, index_codes: list[str]
    ) -> dict:
        """物理删除指数行情缓存行,并连带清 Redis(否则删完仍从缓存读到已删数据)。"""
        deleted = await IndexNavDao.delete_by_codes(query_db, index_codes)
        await query_db.commit()
        for code in index_codes:
            name = _NAME_BY_CODE.get(code)
            if not name:
                continue
            try:
                await AkshareService.clear_index_cache(redis, name)
            except Exception as cache_err:
                logger.warning(f'[指数行情] Redis 清理失败 name={name} | {cache_err}')
        logger.info(f'[指数行情] 缓存已删除 codes={index_codes} 删除行数={deleted}')
        return {'deleted': deleted, 'codes': index_codes}

    # ---------- 内部工具 ----------

    @staticmethod
    def _records_of(row: IndexNavHistory | None) -> list[dict]:
        """从缓存行取出行情记录列表(无行/无数据/结构缺失一律按空处理)。"""
        if row is None or not row.nav_data:
            return []
        records = row.nav_data.get('records')
        return records if isinstance(records, list) else []

    @classmethod
    def _sync_status_of(cls, row: IndexNavHistory | None) -> str:
        """三态同步状态,直出字典 sys_index_sync_status 的 dict_value(日志页范式:字典值贯穿):

        '0'=未同步(无行/无有效记录) / '2'=已过期(有数据但跨失效点未更新) / '1'=已同步(新鲜)。
        判定用双窗口(每天 00:00/22:00 两失效点,与基金净值同口径)。
        读时计算,不落库——"过期"随时间自然发生,无需任何定时任务刷新状态。
        """
        if row is None:
            return '0'
        records = cls._records_of(row)
        if not records:
            return '0'
        if IndexNavDao.is_stale_records(records, row.update_time):
            return '2'
        return '1'

    @staticmethod
    def _fmt_time(value: datetime | None) -> str | None:
        """审计时间统一 yyyy-MM-dd HH:mm:ss 出网,前端直接展示。"""
        return value.strftime('%Y-%m-%d %H:%M:%S') if value else None

    @staticmethod
    def _name_of(index_code: str) -> str:
        """代码反查名称;不在内置清单里的代码直接拒绝(同步/详情只服务内置指数)。"""
        name = _NAME_BY_CODE.get(index_code)
        if not name:
            raise ServiceWarning(message=f'不支持的指数代码:{index_code}')
        return name
