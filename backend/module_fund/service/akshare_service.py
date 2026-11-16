"""AkShare 外部数据服务(基金/指数行情获取)。

统一走三级缓存:Redis → Database → 外部数据源,未命中回写 DB 与 Redis。
akshare 为同步阻塞库,一律经 asyncio.to_thread 包裹,防止阻塞事件循环。
"""

import asyncio
import json
import re
import threading
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd
import requests
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from common.enums import RedisInitKeyConfig
from module_fund.dao.fund_dao import FundDao
from module_fund.dao.fund_nav_dao import FundNavDao
from module_fund.dao.index_nav_dao import IndexNavDao
from utils.log import logger
from utils.nav_window_util import window_ttl

# 指数名称 → Sina symbol 映射(stock_zh_index_daily 是唯一稳定数据源,Eastmoney 接口频繁断连)
BENCHMARK_INDICES = {
    '沪深300': 'sh000300',
    '上证50': 'sh000016',
    '中证500': 'sh000905',
    '科创50': 'sh000688',
    '创业板指': 'sz399006',
}

# 收益率分析的默认基准(与内置清单同处,避免消费方各写一份指数名字面量)
DEFAULT_BENCHMARK_INDEX = '沪深300'

# 无风险利率:中国国债 **2 年期** 收益率的区间均值。为什么不是 1 年期(更主流的期限):
# 1 年期只有中债网(单次请求 10s、一次最多取一年)与货币网(单次仅回最近一个交易日)两个源,
# 都拿不到「秒级 + 全历史」;2 年期走东财单个接口即可拉全历史,可直接算区间均值。
RISK_FREE_RATE_COLUMN = '中国国债收益率2年'
# 国债收益率是日频数据,当天多次请求没必要重复回源;TTL 与指数行情同档
RISK_FREE_RATE_TTL = 6 * 3600
# 取数失败时的兜底年化利率(改造前的固定常量:贴近货币基金收益)
RISK_FREE_RATE_FALLBACK_ANNUAL = 0.015

# V8(js 引擎)崩溃防护:akshare 的 fund_open_fund_info_em 每次调用都新建
# py_mini_racer.MiniRacer(),其 V8 platform 是进程级单例——两线程同时首次创建
# (并发回源竞态)或 fork 后再初始化会触发 address_pool_manager 双重初始化,
# 整个进程直接 FATAL abort(非可捕获异常)。防护双保险:
# ① 预热——import 阶段(单线程)在锁内先建一个实例并模块级保活(防 GC),
#    此后所有线程建实例都跳过 address pool 初始化,竞态窗口消失;
# ② 串行化——_fetch_nav_records 整体持 _akshare_js_lock,与"净值同步需限速"
#    既有约束同向,Redis 缓存命中路径不经过锁零影响
_akshare_js_lock = threading.Lock()

try:
    import py_mini_racer

    with _akshare_js_lock:
        _v8_warmup: Any = py_mini_racer.MiniRacer()
except Exception as e:  # pragma: no cover - 环境缺依赖时仅告警,akshare 调用自身会报错
    _v8_warmup = None
    logger.warning(f'[基金净值] py_mini_racer 预热失败,V8 崩溃防护未生效 | {e}')


def _build_nav_records(df_unit: pd.DataFrame, df_accum: pd.DataFrame | None) -> list[dict]:
    """单位净值 df + 累计净值 df → records 纯组装(无 IO,便于单测锁口径)。

    复权净值 = 日增长率连乘(归一化从 1.0 起)——akshare 无复权净值/因子接口
    ("累计收益率走势"是稀疏采样不可用),日增长率连乘即分红再投资口径的标准自建路径,
    日增长率坏点(=0 但单位净值实际变动,接口数据质量问题)分两类回填:普通坏点日用
    单位净值环比,坏点撞分红除息日用再投资公式(除息下跌非投资损失,环比会把分红
    损失错误计入收益);累计净值(直出字段,非再加工)按净值日期对齐,缺失日回落复权值兜底。
    """
    df = df_unit.copy()
    df['净值日期'] = pd.to_datetime(df['净值日期'])
    df['unit_nav'] = pd.to_numeric(df['单位净值'], errors='coerce')
    raw_dy = pd.to_numeric(df['日增长率'], errors='coerce')
    df = df.sort_values('净值日期').reset_index(drop=True)

    # 每份分红推导(零新增外部调用):恒等式 raw_accum - unit = 累计每份分红
    # (官方口径下 raw_accum 分红日平滑、unit 除息跳水),故 delta 的一阶差分
    # 在分红日恰好等于当日每份分红,非分红日仅为 ±0.0002 的 4 位小数舍入噪声
    unit_prev = df['unit_nav'].shift(1)
    div_per_unit = pd.Series(0.0, index=df.index)
    if df_accum is not None and not df_accum.empty:
        accum_series = pd.to_numeric(df_accum['累计净值'], errors='coerce')
        accum_series.index = pd.to_datetime(df_accum['净值日期'])
        delta = accum_series.reindex(df['净值日期']).to_numpy() - df['unit_nav'].to_numpy()
        div_per_unit = pd.Series(delta, index=df.index).diff().clip(lower=0).fillna(0)
    is_dividend = div_per_unit > 0.001  # 高于舍入噪声,且低于最小真实分红(每份 0.004)留足判别裕度

    # 坏点回填:官方日增长率存在确为 0.0(非 NaN)但单位净值实际变动的坏点日
    # (005827 实测 16 个、008163 实测 3 个,多为节后首日,如 2019-02-11 +5.23% 被记
    # 0),直接连乘会把缺口复利放大(005827 终点差 11.9 个百分点)。官方 dy=0 且
    # |单位净值环比| 超过净值 4 位小数分辨率噪声(~0.01%)即坏点,阈值取 0.05% 时
    # 005827 复权线与单位净值线差收敛 ~0.1%(残余为净值舍入噪声)。回填分两支:
    # 普通坏点日用环比;坏点撞分红日(008163 2025-01-17,dy=0 且环比 -2.06% 其实是
    # 除息)用再投资公式——环比会把分红除息损失错误计入收益
    unit_ret = df['unit_nav'].pct_change() * 100
    reinvest_ret = (df['unit_nav'] + div_per_unit) / unit_prev * 100 - 100
    fill_value = reinvest_ret.where(is_dividend, unit_ret)
    bad_point = (raw_dy.fillna(0) == 0) & (unit_ret.abs() > 0.05)
    df['daily_yield'] = raw_dy.where(~bad_point, fill_value).fillna(0)

    # 复权净值 = 日增长率连乘(归一化从 1.0 起)
    df['factor'] = (1 + df['daily_yield'] / 100).cumprod()
    df['factor'] = df['factor'] / df['factor'].iloc[0]
    df['accum_nav'] = df['factor'].round(4)

    # 原始累计净值按净值日期建索引,与单位净值序列对齐
    accum_map: dict = {}
    if df_accum is not None and not df_accum.empty:
        for _, row in df_accum.iterrows():
            nav_date = pd.to_datetime(row['净值日期']).date()
            value = pd.to_numeric(pd.Series([row['累计净值']]), errors='coerce').iloc[0]
            accum_map[nav_date] = float(value) if pd.notna(value) else None

    records = []
    for _, row in df.iterrows():
        record_date = row['净值日期'].date()
        raw_accum_nav = accum_map.get(record_date)
        if raw_accum_nav is None:
            raw_accum_nav = float(row['accum_nav']) if pd.notna(row['accum_nav']) else 0
        records.append({
            'nav_date': str(record_date),
            'unit_nav': float(row['unit_nav']) if pd.notna(row['unit_nav']) else 0,
            'accum_nav': float(row['accum_nav']) if pd.notna(row['accum_nav']) else 0,
            'raw_accum_nav': raw_accum_nav,
            'daily_yield': float(row['daily_yield']),
        })
    return records


def _fetch_money_yield_records(fund_code: str) -> list[dict]:
    """拉取货币基金收益序列(同步阻塞,调用侧需 to_thread)。

    货币基金没有「单位净值走势」(天天基金 pingzhongdata JS 里不存在
    Data_netWorthTrend 变量,场外接口必抛 ReferenceError),但存在
    Data_sevenDaysYearIncome(七日年化%)与 Data_millionCopiesIncome(每万份收益)。
    两个序列一起取:七日年化供详情页展示,万份收益供合成净值序列。
    records 契约:{nav_date, annualized_7d, per_10k_income}。
    """
    resp = requests.get(
        f'https://fund.eastmoney.com/pingzhongdata/{fund_code}.js',
        headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://fund.eastmoney.com/',
        },
        timeout=30,
    )
    resp.raise_for_status()
    match = re.search(r'var Data_sevenDaysYearIncome\s*=\s*(\[.*?\]);', resp.text, re.S)
    if not match:
        return []
    tz = ZoneInfo('Asia/Shanghai')

    def _date_of(ms: float) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=tz).strftime('%Y-%m-%d')

    income_map: dict[str, float] = {}
    income_match = re.search(r'var Data_millionCopiesIncome\s*=\s*(\[.*?\]);', resp.text, re.S)
    if income_match:
        for ms, value in json.loads(income_match.group(1)):
            income_map[_date_of(ms)] = float(value)
    # 首日占位 0 不进序列(成立当日无七日年化可言)
    return [
        {
            'nav_date': _date_of(ms),
            'annualized_7d': float(value),
            'per_10k_income': income_map.get(_date_of(ms), 0.0),
        }
        for ms, value in json.loads(match.group(1))
        if float(value) > 0
    ]


def _build_money_nav_series(money_records: list[dict]) -> list[dict]:
    """由万份收益合成货币基金净值序列(纯函数)。

    单位净值恒 1.0——市值=份额,这是货币基金的本质;每万份收益 r 元折算成
    日增长率 r/10000(即 daily_yield=r/100,单位与普通基金日增长率一致,%),
    连乘累计进 accum_nav——TWR/分析口径因此能把货基收益计入,而快照市值
    不会因「无净值」被算成 0 或跳过。
    """
    nav_records: list[dict] = []
    accum = 1.0
    for record in money_records:
        income = float(record.get('per_10k_income') or 0)
        daily_yield = income / 100
        accum *= 1 + daily_yield / 100
        nav_records.append({
            'nav_date': record['nav_date'],
            'unit_nav': 1.0,
            'accum_nav': round(accum, 6),
            'raw_accum_nav': round(accum, 6),
            'daily_yield': daily_yield,
        })
    return nav_records


def _fetch_etf_nav_df(fund_code: str) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """场内 ETF/LOF 净值(场外接口不覆盖场内基金):字段转成场外版同构的两个 df。"""
    df = ak.fund_etf_fund_info_em(fund=fund_code, start_date='19900101', end_date='20500101')
    if df is None or df.empty:
        return None
    return df[['净值日期', '单位净值', '日增长率']], df[['净值日期', '累计净值']]


def _fetch_nav_records(fund_code: str) -> list[dict]:
    """经 akshare 官方接口获取基金净值序列(同步阻塞,调用侧需 to_thread)。

    场外开放式基金走 fund_open_fund_info_em(单位净值走势 + 累计净值走势,
    数据源即天天基金 pingzhongdata JS 的官方封装,成立以来全历史逐日);
    空/异常时降级 fund_etf_fund_info_em 覆盖场内 ETF/LOF——不依赖 fund_type
    映射,failover 简单可靠。records 契约:{nav_date, unit_nav, accum_nav, raw_accum_nav, daily_yield}。
    """
    # 持全局锁串行化:MiniRacer 实例创建虽已预热消除竞态,但锁同时兜住
    # fork 场景与 akshare 内部其它非常量级共享状态;缓存命中路径不经过本函数
    with _akshare_js_lock:
        try:
            df_unit = ak.fund_open_fund_info_em(symbol=fund_code, indicator='单位净值走势')
            df_accum = ak.fund_open_fund_info_em(symbol=fund_code, indicator='累计净值走势')
            if df_unit is not None and not df_unit.empty:
                return _build_nav_records(df_unit, df_accum)
        except Exception as e:
            logger.warning(f'[基金净值] akshare 场外接口获取失败,尝试场内降级 fund_code={fund_code} | {e}')
        try:
            etf_df = _fetch_etf_nav_df(fund_code)
            if etf_df:
                records = _build_nav_records(*etf_df)
                # 场内接口对场外代码不报错而是返回错位数据(实证:货币基金的万份收益
                # 序列被当单位净值入库,accum_nav 连乘出 1e+68)——荒谬值一律丢弃,
                # 宁可空数据交待确认/空态,不能把垃圾当行情;raw_accum_nav 一并校验,
                # 它直接来自源数据不经复权连乘,单看 accum_nav 会漏掉日增长全 0 的错位数据
                if records and max(
                    max(r['accum_nav'], r.get('raw_accum_nav') or 0) for r in records
                ) < 1e6 and all(r['unit_nav'] > 0 for r in records):
                    return records
                logger.warning(f'[基金净值] 场内接口返回数据不合理,已丢弃 fund_code={fund_code}')
                return []
        except Exception as e:
            logger.warning(f'[基金净值] akshare 场内接口获取失败 fund_code={fund_code} | {e}')
        return []


async def _cache_get(redis: aioredis.Redis, key: str) -> Any:
    """读 Redis JSON 缓存,未命中返回 None。"""
    cached = await redis.get(key)
    return json.loads(cached) if cached else None


async def _cache_set(redis: aioredis.Redis, key: str, value: Any, ttl: int) -> None:
    """写 Redis JSON 缓存(带 TTL)。"""
    await redis.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)


def fetch_risk_free_rate_series() -> list[dict]:
    """拉取中国国债 2 年期收益率全历史(东财源,同步阻塞,调用侧需 to_thread)。

    源返回 13 列 6000+ 行且含美债与 GDP 列,这里只留日期与 2 年期收益率两列——整条序列
    要进 Redis,不瘦身等于把整张表塞进缓存。起点固定 2004-01-01(与「成立以来」档的
    数据年代下限一致),可覆盖任何档位的区间。
    """
    df = ak.bond_zh_us_rate(start_date='20040101')
    df = df[['日期', RISK_FREE_RATE_COLUMN]].dropna()
    df = df.sort_values('日期')
    return [
        {'date': pd.to_datetime(row['日期']).strftime('%Y-%m-%d'), 'yield': float(row[RISK_FREE_RATE_COLUMN])}
        for _, row in df.iterrows()
    ]


def mean_yield_in_window(records: list[dict], start_date: date, end_date: date) -> float | None:
    """区间内收益率的算术平均(返回**小数**年化);区间内无数据返回 None 交给调用侧降级。

    口径:把该区间当成被测持有期,用区间内的平均无风险利率折年化超额。QuantStats 的
    `sharpe` / `rolling_sharpe` 只接受**标量** rf,所以整段(含滚动夏普)共用一个均值。
    """
    start, end = start_date.isoformat(), end_date.isoformat()
    window = [r['yield'] for r in records if start <= r['date'] <= end]
    if not window:
        return None
    return sum(window) / len(window) / 100


def fetch_index_history(symbol: str) -> list[dict]:
    """拉取单个指数的完整历史行情(新浪源,同步阻塞,调用侧需 to_thread)。

    返回字段:nav_date/close/open/high/low/volume/daily_yield,按日期升序。
    daily_yield 为按收盘价自行计算的日涨跌幅(新浪接口无该列),首行无前日 → 0.0。
    """
    df = ak.stock_zh_index_daily(symbol=symbol)
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    df = df.sort_values('date').reset_index(drop=True)
    df['daily_yield'] = df['close'].pct_change() * 100
    records = []
    for _, row in df.iterrows():
        records.append({
            'nav_date': row['date'],
            'close': float(row['close']),
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'volume': int(row['volume']) if pd.notna(row['volume']) else 0,
            'daily_yield': round(float(row['daily_yield']), 4) if pd.notna(row['daily_yield']) else 0.0,
        })
    return records


class AkshareService:
    """基金/指数行情数据服务(三级缓存编排)。"""

    @classmethod
    async def get_all_funds_from_akshare(cls) -> list[dict]:
        """从 AkShare 获取全部基金基本信息(代码/简称/类型)。

        用 fund_name_em 而不是 fund_open_fund_daily_em:前者返回的是基金**档案**信息(自带基金类型,
        34 种细粒度取值),后者只是每日净值快照——没有类型列且列名内嵌日期,早前只能拿它凑合、
        再靠名称关键词猜类型。
        """

        def _fetch() -> list[dict]:
            # fund_name_em 的列名是稳定契约(区别于净值接口的日期内嵌列名),故按列名取值
            df = ak.fund_name_em()
            funds = []
            for _, row in df.iterrows():
                funds.append({
                    'code': str(row['基金代码']),
                    'name': str(row['基金简称']),
                    'fund_type': str(row['基金类型']),
                    'status': '0',
                })
            return funds

        # fund_name_em 是同步阻塞的网络调用,必须丢线程池,否则会卡住整个事件循环
        return await asyncio.to_thread(_fetch)

    @staticmethod
    def is_money_fund_type(fund_type: str | None) -> bool:
        """按 fund_type 判断是否货币基金(如「货币型-普通货币」)。"""
        return '货币' in (fund_type or '')

    @classmethod
    async def is_money_fund(cls, query_db: AsyncSession, fund_code: str) -> bool:
        """查库判断基金是否货币基金(基金不存在按 False,让既有报错路径生效)。"""
        fund = await FundDao.get_fund_by_code(query_db, fund_code)
        return cls.is_money_fund_type(fund.fund_type) if fund else False

    @classmethod
    async def get_fund_nav(cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str) -> list[dict]:
        """获取基金历史净值(复权净值视图,收益率走势用)。

        返回字段:nav_date/unit_nav/accum_nav/raw_accum_nav/daily_yield。
        货币基金返回合成序列:单位净值恒 1.0、万份收益折日增长累计进 accum_nav,
        不回源净值接口、不落 fund_nav_history(回源只会拉回万份收益错位成的
        垃圾数据,实证事故 2026-10-08)。消费方(持仓市值/快照/分析)由此统一
        拿到正确口径,无需各自特判。
        """
        if await cls.is_money_fund(query_db, fund_code):
            return await cls.get_money_fund_nav_series(query_db, redis, fund_code)
        cache_key = f'{RedisInitKeyConfig.FUND_NAV.key}:{fund_code}'
        cached = await _cache_get(redis, cache_key)
        if cached:
            return cached
        db_records = await FundNavDao.get_nav_history(query_db, fund_code)
        if db_records and not await FundNavDao.is_nav_stale(query_db, fund_code):
            await _cache_set(redis, cache_key, db_records, window_ttl(datetime.now()))
            return db_records
        records = await asyncio.to_thread(_fetch_nav_records, fund_code)
        if not records:
            return []
        await FundNavDao.upsert_nav_history(query_db, fund_code, records)
        await query_db.commit()
        await _cache_set(redis, cache_key, records, window_ttl(datetime.now()))
        return records

    @classmethod
    async def get_raw_fund_nav(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str
    ) -> Optional[list[dict]]:
        """获取基金原始净值(净值走势用,失败返回 None 以区分"无原始累计净值"与"空数据")。

        货币基金恒返回 None(没有净值,同 get_fund_nav 的守卫理由)。
        """
        if await cls.is_money_fund(query_db, fund_code):
            return None
        cache_key = f'{RedisInitKeyConfig.FUND_NAV_RAW.key}:{fund_code}'
        cached = await _cache_get(redis, cache_key)
        if cached:
            return cached
        db_records = await FundNavDao.get_nav_history(query_db, fund_code)
        if db_records and not await FundNavDao.is_nav_stale(query_db, fund_code):
            await _cache_set(redis, cache_key, db_records, window_ttl(datetime.now()))
            return db_records
        records = await asyncio.to_thread(_fetch_nav_records, fund_code)
        if not records:
            return None
        await FundNavDao.upsert_nav_history(query_db, fund_code, records)
        await query_db.commit()
        await _cache_set(redis, cache_key, records, window_ttl(datetime.now()))
        return records

    @classmethod
    async def resolve_target_nav(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str, target_date
    ) -> Optional[tuple[str, float]]:
        """解析目标净值日(严格语义,交易确认专用)。

        优先精确匹配 target_date;所选日期为非交易日时顺延到 nav_date ≥ target
        的第一条(下一交易日)。目标净值日尚未发布(盘中/晚间 22 点前/周末录入)
        返回 None——调用方应落库为待确认,不要回落最新值:那会让 9/7 的买入
        按 9/4 的净值算份额。
        货币基金特例:单位净值恒为 1.0 且无「待发布」概念,任意日期直接返回
        (target_date, 1.0)——不回源、不待确认,建仓/买入/赎回/重建重放全走这条。
        """
        if await cls.is_money_fund(query_db, fund_code):
            target_str = target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date)
            return target_str, 1.0
        records = await cls.get_fund_nav(query_db, redis, fund_code)
        if not records:
            return None
        target_str = target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date)
        for record in records:
            if record.get('nav_date') == target_str:
                return target_str, record.get('unit_nav') or 0
        for record in records:
            if (record.get('nav_date') or '') >= target_str:
                return record.get('nav_date'), record.get('unit_nav') or 0
        return None

    @classmethod
    async def get_money_fund_yield(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str
    ) -> list[dict]:
        """获取货币基金收益序列(七日年化 + 每万份收益,基金详情页与净值合成的数据源)。

        只走 Redis 缓存 → pingzhongdata 回源,不落 fund_nav_history——那张表的
        字段语义(unit_nav/accum_nav/日增长率)对货币基金全部不成立,入库会被
        复权连乘与 QuantStats 当真实净值消费。非货币基金返回空。
        回源失败(网络/限流)只告警返回空,**绝不抛异常**——否则整条快照重建
        会被一只基金的回源失败拖崩(快照写入是清空重写模式)。
        """
        if not await cls.is_money_fund(query_db, fund_code):
            return []
        cache_key = f'{RedisInitKeyConfig.MONEY_FUND_YIELD.key}:{fund_code}'
        cached = await _cache_get(redis, cache_key)
        if cached:
            return cached
        try:
            records = await asyncio.to_thread(_fetch_money_yield_records, fund_code)
        except Exception as e:
            logger.warning(f'[货基收益] pingzhongdata 回源失败,本次按空序列处理 fund_code={fund_code} | {e}')
            return []
        if not records:
            return []
        await _cache_set(redis, cache_key, records, window_ttl(datetime.now()))
        return records

    @classmethod
    async def get_money_fund_nav_series(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str
    ) -> list[dict]:
        """货币基金合成净值序列(内存派生,不落库),与普通基金净值同构。

        消费 get_money_fund_yield 的缓存,经 _build_money_nav_series 合成:
        unit_nav 恒 1.0、accum_nav 由万份收益连乘。持仓市值/快照/分析等
        净值消费方无需感知货币基金特例。
        """
        money_records = await cls.get_money_fund_yield(query_db, redis, fund_code)
        return _build_money_nav_series(money_records)

    @classmethod
    async def get_benchmark_nav(
        cls, query_db: AsyncSession, redis: aioredis.Redis, benchmark_names: list[str]
    ) -> dict[str, list[dict]]:
        """获取多个指数的完整历史行情(收盘点位,时间范围过滤由 ChartService 负责)。"""

        result: dict[str, list[dict]] = {}
        for name in benchmark_names:
            symbol = BENCHMARK_INDICES.get(name)
            if not symbol:
                continue
            cache_key = f'{RedisInitKeyConfig.INDEX_NAV.key}:{name}'
            cached = await _cache_get(redis, cache_key)
            if cached:
                result[name] = cached
                continue
            db_records = await IndexNavDao.get_nav_history(query_db, symbol)
            if db_records and not await IndexNavDao.is_nav_stale(query_db, symbol):
                await _cache_set(redis, cache_key, db_records, window_ttl(datetime.now()))
                result[name] = db_records
                continue
            try:
                records = await asyncio.to_thread(fetch_index_history, symbol)
                if records:
                    await IndexNavDao.upsert_nav_history(query_db, symbol, name, records)
                    await query_db.commit()
                    await _cache_set(redis, cache_key, records, window_ttl(datetime.now()))
                result[name] = records
            except Exception as e:
                # 单个指数失败不阻断其余指数(对比图缺一条仍可用)
                logger.warning(f'[指数行情] 获取失败 name={name} symbol={symbol} | {e}')
                result[name] = []
        return result

    @classmethod
    async def refresh_index_cache(cls, redis: aioredis.Redis, index_name: str, records: list[dict]) -> None:
        """强制同步后回填/覆盖 Redis 指数缓存(键用指数中文名,与缓存读取路径一致)。"""
        await _cache_set(
            redis, f'{RedisInitKeyConfig.INDEX_NAV.key}:{index_name}', records, window_ttl(datetime.now())
        )

    @classmethod
    async def clear_index_cache(cls, redis: aioredis.Redis, index_name: str) -> None:
        """清掉某指数的 Redis 缓存(删除缓存行时必须连带,否则仍从缓存读到已删数据)。"""
        await redis.delete(f'{RedisInitKeyConfig.INDEX_NAV.key}:{index_name}')

    @classmethod
    async def get_risk_free_rate_annual(cls, redis: aioredis.Redis, start_date: date, end_date: date) -> float:
        """无风险利率(年化小数)= 区间内中国国债 2 年期收益率的均值;取不到则回退固定值。

        只缓存**整条收益率序列**(不按窗口缓存):一次回源即可覆盖所有档位。收益率是
        外部辅助序列、且不像基金/指数净值那样有用户可维护的入库路径,故只走 Redis
        一层(不落 DB),与 `get_benchmark_nav` 的三级缓存有意不同。
        """
        cache_key = f'{RedisInitKeyConfig.RISK_FREE_RATE.key}:series'
        records = await _cache_get(redis, cache_key)
        if not records:
            try:
                records = await asyncio.to_thread(fetch_risk_free_rate_series)
            except Exception as e:
                logger.warning(f'[无风险利率] 获取失败,降级固定 {RISK_FREE_RATE_FALLBACK_ANNUAL} | {e}')
                return RISK_FREE_RATE_FALLBACK_ANNUAL
            if records:
                await _cache_set(redis, cache_key, records, RISK_FREE_RATE_TTL)
        rate = mean_yield_in_window(records or [], start_date, end_date)
        if rate is None:
            logger.warning(
                f'[无风险利率] 区间内无数据 {start_date}~{end_date},降级固定 {RISK_FREE_RATE_FALLBACK_ANNUAL}'
            )
            return RISK_FREE_RATE_FALLBACK_ANNUAL
        return rate
