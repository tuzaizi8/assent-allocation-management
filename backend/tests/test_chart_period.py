"""图表时间档过滤(filter_records_by_period)单元测试。

覆盖三块:
① 真相源一致性:CHART_PERIODS 显式列表与 PERIOD_DELTAS 键集严格对齐(显式列表后防失配的锁)
② 三个特殊语义档位:3年(固定步长)/今年来(年初起算)/成立以来(直通全量)
③ 边界行为:起始日非交易日取"不超过起始日的最近交易日"(往前取策略)、未识别档位退化为全量
④ 显式区间过滤:自定义时间档的"往前取"与越界(早于/晚于全部数据、反序)行为
"""

from datetime import date

from module_fund.service.chart_service import (
    CHART_PERIODS,
    PERIOD_ALL,
    PERIOD_DELTAS,
    PERIOD_YTD,
    ChartService,
)


def make_records(dates: list[str]) -> list[dict]:
    """构造净值记录(过滤逻辑只依赖 nav_date,close 仅为结构完整)。"""
    return [{'nav_date': d, 'close': 1.0 + i * 0.1} for i, d in enumerate(dates)]


class TestPeriodsConsistency:
    """真相源一致性:显式列表与 delta 表不得失配"""

    def test_delta_keys_subset_of_periods(self):
        assert set(PERIOD_DELTAS) < set(CHART_PERIODS)

    def test_no_duplicate_periods(self):
        assert len(CHART_PERIODS) == len(set(CHART_PERIODS))

    def test_special_periods_not_in_delta_table(self):
        assert PERIOD_YTD not in PERIOD_DELTAS
        assert PERIOD_ALL not in PERIOD_DELTAS

    def test_periods_order(self):
        # 顺序即前端下拉展示顺序,变更须同步 02 逐行讲解文档
        assert CHART_PERIODS == [
            '1周',
            '1月',
            '3月',
            '6月',
            '1年',
            '3年',
            '5年',
            '今年来',
            '成立以来',
        ]


class TestFilterByPeriod:
    def test_period_all_returns_all(self):
        records = make_records(['2026-01-01', '2026-03-01', '2026-06-15'])
        assert ChartService.filter_records_by_period(records, PERIOD_ALL) is records

    def test_3y_starts_from_boundary(self):
        records = make_records(
            ['2023-06-10', '2023-06-20', '2024-01-01', '2026-06-15']
        )
        result = ChartService.filter_records_by_period(records, '3年')
        # start=2023-06-15,不超过起始日的最近交易日是 2023-06-10
        assert result[0]['nav_date'] == '2023-06-10'
        assert len(result) == 4

    def test_ytd_starts_from_year_start(self):
        records = make_records(
            ['2025-06-01', '2025-12-31', '2026-01-05', '2026-06-15']
        )
        result = ChartService.filter_records_by_period(records, PERIOD_YTD)
        # 年初 1/1 当日无记录 → 往前取策略落到 2025-12-31 作基准日
        assert result[0]['nav_date'] == '2025-12-31'
        assert len(result) == 3

    def test_ytd_first_day_has_record(self):
        records = make_records(['2026-01-01', '2026-06-15'])
        result = ChartService.filter_records_by_period(records, PERIOD_YTD)
        assert result[0]['nav_date'] == '2026-01-01'

    def test_1week_boundary(self):
        records = make_records(['2026-06-01', '2026-06-08', '2026-06-15'])
        result = ChartService.filter_records_by_period(records, '1周')
        # start=2026-06-08,边界日恰有记录
        assert result[0]['nav_date'] == '2026-06-08'
        assert len(result) == 2

    def test_unknown_period_falls_back_to_all(self):
        records = make_records(['2020-01-01', '2026-06-15'])
        # 未识别档位宽松退化:兼容旧客户端缓存的档位值
        assert ChartService.filter_records_by_period(records, '2年') is records


class TestFilterByDateRange:
    """按显式区间过滤(前端自定义时间档):"往前取"与档位同口径,越界一律不抛异常"""

    RECORDS = ['2026-06-05', '2026-06-08', '2026-06-12', '2026-06-15']

    def test_range_inside_returns_slice(self):
        records = make_records(self.RECORDS)
        result = ChartService.filter_records_by_date_range(
            records, date(2026, 6, 8), date(2026, 6, 12)
        )
        assert [r['nav_date'] for r in result] == ['2026-06-08', '2026-06-12']

    def test_start_on_non_trading_day_takes_previous(self):
        records = make_records(self.RECORDS)
        # 2026-06-06 是周六:首点取不超过它的最近交易日 06-05,保证区间首日有值可归一化
        result = ChartService.filter_records_by_date_range(
            records, date(2026, 6, 6), date(2026, 6, 12)
        )
        assert result[0]['nav_date'] == '2026-06-05'

    def test_end_on_non_trading_day_takes_previous(self):
        records = make_records(self.RECORDS)
        # 2026-06-13 是周六:末点取不超过它的最近交易日 06-12
        result = ChartService.filter_records_by_date_range(
            records, date(2026, 6, 8), date(2026, 6, 13)
        )
        assert result[-1]['nav_date'] == '2026-06-12'

    def test_start_before_all_records(self):
        records = make_records(self.RECORDS)
        result = ChartService.filter_records_by_date_range(
            records, date(2004, 1, 1), date(2026, 6, 8)
        )
        # 起点早于全部数据:从最早一条开始,不用 0 伪造区间
        assert result[0]['nav_date'] == '2026-06-05'
        assert len(result) == 2

    def test_range_after_all_records_returns_empty(self):
        records = make_records(self.RECORDS)
        assert (
            ChartService.filter_records_by_date_range(
                records, date(2026, 7, 1), date(2026, 7, 31)
            )
            == []
        )

    def test_reversed_range_returns_empty(self):
        records = make_records(self.RECORDS)
        # 前端会就地夹紧,这里只钉"反序不抛异常、返回空表"
        assert (
            ChartService.filter_records_by_date_range(
                records, date(2026, 6, 12), date(2026, 6, 8)
            )
            == []
        )

    def test_unparsable_dates_pass_through(self):
        records = [{'nav_date': '--', 'close': 1.0}]
        # 与档位口径一致:日期全解析不出时不误裁剪,原样返回
        assert (
            ChartService.filter_records_by_date_range(
                records, date(2026, 6, 1), date(2026, 6, 30)
            )
            is records
        )
