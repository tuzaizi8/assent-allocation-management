"""基金图表数据 Service(业务逻辑层)。

职责:收益率曲线/原始净值走势/指数收益率的数据加工与时间段过滤。
"""

from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from module_fund.service.akshare_service import AkshareService

# 时间档唯一真相源:固定步长档位 → 回溯步长。新增固定步长档位只改这里,
# 选项端点/接口描述/指数详情收益率三处消费方同步生效(此前四处各写一份,已出现 5 档/6 档/7 档漂移)
PERIOD_DELTAS: dict[str, relativedelta] = {
    '1周': relativedelta(weeks=1),
    '1月': relativedelta(months=1),
    '3月': relativedelta(months=3),
    '6月': relativedelta(months=6),
    '1年': relativedelta(years=1),
    '3年': relativedelta(years=3),
    '5年': relativedelta(years=5),
}

# 两个无固定步长的特殊档位:relativedelta 表达不了"从年初起算","成立以来"为直通全量
PERIOD_YTD = '今年来'
PERIOD_ALL = '成立以来'

# 选项端点与指数详情收益率按此顺序出网(显式列表而非推导:今年来 须插在 5年 之后,顺序才可控);
# delta 表与列表的一致性由 tests/test_chart_period.py 锁死
CHART_PERIODS: list[str] = [
    '1周',
    '1月',
    '3月',
    '6月',
    '1年',
    '3年',
    '5年',
    PERIOD_YTD,
    PERIOD_ALL,
]


class ChartService:
    """基金/指数图表数据服务。"""

    @staticmethod
    def _parse_record_date(value) -> datetime | None:
        """行情/净值日期解析:兼容 yyyy-MM-dd 与 yyyyMMdd,解析不出返回 None"""
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(str(value), fmt)
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _date_index(cls, records: list) -> list[tuple[datetime, int]]:
        """(交易日, 下标) 升序;解析不出的记录不进索引"""
        pairs = []
        for idx, record in enumerate(records):
            parsed = cls._parse_record_date(record.get("nav_date"))
            if parsed is not None:
                pairs.append((parsed, idx))
        pairs.sort()
        return pairs

    @classmethod
    def filter_records_by_period(cls,records: list, period: str) -> list:
        """按时间段过滤净值记录("往前取"策略,与天天基金一致)。

        起始日非交易日时,取不超过起始日的最近交易日——保证区间首日有净值可归一化。
        """
        if not records or period == PERIOD_ALL:
            return records

        latest_date = cls._parse_record_date(records[-1].get("nav_date"))
        if latest_date is None:
            return records

        if period == PERIOD_YTD:
            # 年初起算(YTD):1 月 1 日非交易日时由下方查找逻辑自然落到不超过起始日的最近交易日
            start_date = latest_date.replace(month=1, day=1)
        else:
            delta = PERIOD_DELTAS.get(period)
            if not delta:
                # 未识别档位退化为全量而非报错:档位集合由后端下发,兼容旧客户端缓存的档位值
                return records
            start_date = latest_date - delta

        pairs = cls._date_index(records)
        if not pairs:
            return records

        # 找不超过 start_date 的最近交易日索引
        base_idx = None
        for record_date, idx in pairs:
            if record_date <= start_date:
                base_idx = idx
            elif base_idx is not None:
                break

        if base_idx is None:
            base_idx = 0

        return records[base_idx:]

    @classmethod
    def filter_records_by_date_range(cls, records: list, start_date: date, end_date: date) -> list:
        """按显式日期区间过滤("往前取"与档位口径一致:起始日非交易日取不超过它的最近交易日)。

        区间内一个交易日都没有时返回空表:否则"起始日晚于全部数据"会靠往前取落到最后一根,
        拿区间外的那一个点画出假曲线(如把未来起始日画成一根孤点)。
        """
        pairs = cls._date_index(records)
        if not pairs:
            return records  # 与档位口径一致:日期全解析不出时不误裁剪

        if not any(start_date <= record_date.date() <= end_date for record_date, _ in pairs):
            return []

        base_idx = None
        end_idx = None
        for record_date, idx in pairs:
            if record_date.date() <= start_date:
                base_idx = idx
            if record_date.date() <= end_date:
                end_idx = idx

        if base_idx is None:
            base_idx = pairs[0][1]  # 区间起点早于全部数据:从最早一条开始
        return records[base_idx : end_idx + 1]



    @classmethod
    async def get_yield_curve(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str, period: str
    ) -> dict:
        """获取基金收益率曲线数据(复权净值视图,accum_nav 归一化为首日=1.0,与指数曲线同构)。

        货币基金分支:没有净值曲线,改返回七日年化序列(data 项为
        {nav_date, annualized_7d},值为百分比)并带 is_money_fund 标记,
        前端据此切换为「七日年化走势」单线展示,不取基准对比。
        """
        if await AkshareService.is_money_fund(query_db, fund_code):
            records = await AkshareService.get_money_fund_yield(query_db, redis, fund_code)
            filtered_records = cls.filter_records_by_period(records, period)
            return {
                'fund_code': fund_code,
                'period': period,
                'data': filtered_records,
                'is_money_fund': True,
            }
        all_records = await AkshareService.get_fund_nav(query_db, redis, fund_code)
        filtered_records = cls.filter_records_by_period(all_records, period)
        if not filtered_records:
            return {'fund_code': fund_code, 'period': period, 'data': []}

        # 归一化(照 get_index_yield 先例):以过滤后首日 accum_nav 为基准,全序列 1.0 起步——
        # akshare 原始累计净值非 1.0 起步,直接透传会使前端 (x−1)×100 换算失真
        base_accum = filtered_records[0].get('accum_nav') or 1
        result = [
            {**record, 'accum_nav': round(record['accum_nav'] / base_accum, 4)}
            for record in filtered_records
        ]
        return {'fund_code': fund_code, 'period': period, 'data': result}

    @classmethod
    async def get_raw_nav(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_code: str, period: str
    ) -> dict:
        """获取基金原始净值走势数据(原始累计净值,来自 Eastmoney Data_ACWorthTrend)。"""
        raw_records = await AkshareService.get_raw_fund_nav(query_db, redis, fund_code)
        if raw_records is None:
            return {
                'fund_code': fund_code,
                'period': period,
                'data': [],
                'has_raw_accum_nav': False,
            }
        filtered = cls.filter_records_by_period(raw_records, period)
        return {
            'fund_code': fund_code,
            'period': period,
            'data': filtered,
            'has_raw_accum_nav': True,
        }

    @classmethod
    async def get_index_yield(
        cls,
        query_db: AsyncSession,
        redis: aioredis.Redis,
        index_name: str,
        period: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict:
        """获取指数收益率曲线数据(收盘点位归一化为 accum_nav,与基金收益率曲线同构)。

        给了 start_date/end_date 就走显式区间(前端"自定义"档),缺省口径与
        /portfolio/analytics/risk-metrics 对齐:end 默认今天、start 默认 end 前 365 天。
        """
        all_records_dict = await AkshareService.get_benchmark_nav(query_db, redis, [index_name])
        all_records = all_records_dict.get(index_name, [])
        if not all_records:
            return {'index_name': index_name, 'period': period, 'data': []}

        if start_date or end_date:
            target_end = end_date or date.today()
            target_start = start_date or target_end - timedelta(days=365)
            filtered = cls.filter_records_by_date_range(all_records, target_start, target_end)
        else:
            filtered = cls.filter_records_by_period(all_records, period)
        if not filtered:
            return {'index_name': index_name, 'period': period, 'data': []}

        base_close = filtered[0]['close']
        result = [
            {
                'nav_date': record['nav_date'],
                'close': record['close'],
                'accum_nav': round(record['close'] / base_close, 4),
                'daily_yield': record.get('daily_yield', 0),
            }
            for record in filtered
        ]
        return {'index_name': index_name, 'period': period, 'data': result}
