"""TWR/MWR 现金流剥离口径单测(同日买卖的净额化陷阱)。

对齐真实数据踩到的坑:同一天既有买入又有赎回时,现金流表的 `cash_flow` 是当日净额,
按「净额为正才算赎回」剥离会取不到那笔赎回 → 它凭空变成亏损。剥离必须用
「当日申购总额 / 当日赎回总额」。纯函数直接测,无需 mock(样板对齐 test_daily_fund_profit.py)。
"""

from datetime import date

from module_portfolio.service.analytics_service import (
    AnalyticsService,
    _oversell_days,
    _removed_value_by_date,
)

D0 = date(2026, 9, 8)
D1 = date(2026, 9, 9)
D2 = date(2026, 9, 10)


def make_daily(values: list[float], dates: list[date]) -> list[dict]:
    """构造 daily_data(只有 total_value 参与剥离计算)。"""
    return [{'date': d, 'total_value': v, 'total_invested': 0.0} for d, v in zip(dates, values)]


def segment_return(pair: tuple[float, float]) -> float:
    """段收益率(%),保留两位。"""
    adjusted_bmv, adjusted_emv = pair
    return round((adjusted_emv / adjusted_bmv - 1) * 100, 2)


class TestAdjustedPair:
    """单段市值调整:赎回剥离期初、申购剥离期末。"""

    def test_redemption_stripped_from_opening(self):
        """前一采样日的赎回总额从期初市值剥离(赎回按成交日就已离场,也是期初事件)。"""
        data = make_daily([11308.03, 14184.81], [D0, D1])
        pair = AnalyticsService.adjusted_pair(data, [D0, D1], {}, {D0: 98.99}, 1)
        assert pair == (11308.03 - 98.99, 14184.81)

    def test_purchase_counts_into_opening_not_closing(self):
        """申购计入**当段期初**(不是期末):那笔钱当天就承担涨跌;上一段的申购不参与本段。"""
        data = make_daily([1000.0, 2000.0], [D0, D1])
        # D1(当段末日)发生的申购 → 计进该段期初
        assert AnalyticsService.adjusted_pair(data, [D0, D1], {D1: 500.0}, {}, 1) == (1500.0, 2000.0)
        # D0(上一段)的申购是上一段的事,不参与本段
        assert AnalyticsService.adjusted_pair(data, [D0, D1], {D0: 500.0}, {}, 1) == (1000.0, 2000.0)

    def test_mid_period_flow_is_corrected(self):
        """回归:落在两个采样点之间的买卖必须参与修正——2026-10-08 实证:
        350 买入单周 +34%、700 赎回单周 −30% 全被当成收益/亏损(货币基金回溯录入)。
        修正窗口已从「采样日当天」升级为整个采样区间:申购 (T0,T1]、赎回 [T0,T1)。
        流动日 D1 不在采样序列里,夹在 D0 与 D2 之间。"""
        data = make_daily([1000.0, 1350.0], [D0, D2])
        # 申购在 D1:计期初 → 该段不得把 350 当收益
        pair = AnalyticsService.adjusted_pair(data, [D0, D2], {D1: 350.0}, {}, 1)
        assert pair == (1000.0 + 350.0, 1350.0)
        # 赎回在 D1:期初剥离(市值族 D0 仍持有 1350,D2 只剩 1000)
        data2 = make_daily([1350.0, 1000.0], [D0, D2])
        pair2 = AnalyticsService.adjusted_pair(data2, [D0, D2], {}, {D1: 350.0}, 1)
        assert pair2 == (1350.0 - 350.0, 1000.0)

    def test_same_day_buy_and_sell_is_not_netted_away(self):
        """真实数据复算:09-08 同日买入 11100.00 + 赎回 98.99。

        总额口径 + 申购计期初 → 该段 **−0.94%**;
        旧口径(申购扣期末)得 −1.20%；净额口径(−11001.01 取不到那笔赎回)得 −2.06%。
        三组数并列:锁死「不能用净额」这条回归,同时钉住本期改的申购时点。
        """
        opening_value = 11308.03
        closing_value = 14184.81
        purchase_today = 3110.00

        pair = AnalyticsService.adjusted_pair(
            make_daily([opening_value, closing_value], [D0, D1]),
            [D0, D1],
            {D1: purchase_today},
            {D0: 98.99},
            1,
        )
        assert pair is not None
        assert pair == (opening_value + purchase_today - 98.99, closing_value)
        assert segment_return(pair) == -0.94

        old_closing_strip = (closing_value - purchase_today) / (opening_value - 98.99) - 1
        assert round(old_closing_strip * 100, 2) == -1.20
        netted = (closing_value - purchase_today) / opening_value - 1
        assert round(netted * 100, 2) == -2.06

    def test_uncomputable_without_opening_value(self):
        """期初市值为 0(建仓前)→ None。"""
        data = make_daily([0.0, 100.0], [D0, D1])
        assert AnalyticsService.adjusted_pair(data, [D0, D1], {}, {}, 1) is None

    def test_uncomputable_when_opening_fully_redeemed(self):
        """期初被赎回额扣成 0 → None(避免除零/负基数)。"""
        data = make_daily([100.0, 500.0], [D0, D1])
        assert AnalyticsService.adjusted_pair(data, [D0, D1], {}, {D0: 100.0}, 1) is None


class TestPurchaseAsOpeningEvent:
    """申购计期初:2021-03 建仓初期的真实案例(导出件的记录日是确认日 T+1,份额按 T 日净值成交)。

    旧口径把申购从期末扣掉,等于假设那笔钱"当天收盘才进来",于是每笔买入的次一采样日
    都会多扣一次当天的涨跌;建仓初期本金小(一笔买入占组合 200%~700%)⇒ 被放大成 ±5% 的假波动。
    """

    def test_early_build_up_no_longer_fakes_a_drop(self):
        """03-23 → 03-24:期初 9.91 + 当日申购 20.00、期末 29.33 → −1.94%(旧口径 −5.85%)。"""
        data = make_daily([9.91, 29.33], [D0, D1])
        pair = AnalyticsService.adjusted_pair(data, [D0, D1], {D1: 20.00}, {}, 1)
        assert pair == (29.91, 29.33)
        assert segment_return(pair) == -1.94
        # 旧口径:申购从期末扣掉 → 同一段被算成 −5.85%,差额就是那笔钱当天真实承担的跌幅
        assert round(((29.33 - 20.00) / 9.91 - 1) * 100, 2) == -5.85

    def test_early_build_up_no_longer_fakes_a_rise(self):
        """镜像:03-29 → 03-30 期初 29.54 + 当日申购 80.00、期末 111.18 → +1.50%(旧口径 +5.55%)。"""
        data = make_daily([29.54, 111.18], [D0, D1])
        pair = AnalyticsService.adjusted_pair(data, [D0, D1], {D1: 80.00}, {}, 1)
        # 用算式而非字面量做期望:浮点下 29.54 + 80.00 = 109.53999999999999
        assert pair == (29.54 + 80.00, 111.18)
        assert segment_return(pair) == 1.5
        assert round(((111.18 - 80.00) / 29.54 - 1) * 100, 2) == 5.55

    def test_cash_dividend_kept_on_closing_side(self):
        """现金分红(负额)仍计入期末:除息后 982.44 + 回款 17.56 / 除息前 1000 → 0%(分红不产生收益)。

        若把负额也当「期初事件」加到期初(1000 − 17.56),这段会被算成 +1.79% 的假涨。
        """
        data = make_daily([1000.0, 982.44], [D0, D1])
        pair = AnalyticsService.adjusted_pair(data, [D0, D1], {D1: -17.56}, {}, 1)
        assert pair == (1000.0, 1000.0)
        assert segment_return(pair) == 0.0

    def test_first_day_with_purchase_still_uncomputable(self):
        """建仓首日(期初市值 0)即使当天有申购也不产生段收益:守卫优先,不制造假波动。"""
        data = make_daily([0.0, 100.0], [D0, D1])
        assert AnalyticsService.adjusted_pair(data, [D0, D1], {D1: 100.0}, {}, 1) is None


class TestTwrSeries:
    """100 基准累积序列。"""

    def test_starts_at_100_and_compounds(self):
        data = make_daily([1000.0, 1100.0, 1210.0], [D0, D1, D2])
        assert AnalyticsService.calculate_twr(data, [D0, D1, D2], {}, {}) == [100.0, 110.0, 121.0]

    def test_keeps_previous_value_when_segment_uncomputable(self):
        """建仓那段不可计算 → 曲线保持前一值(不制造假的 0% 波动)。"""
        data = make_daily([0.0, 100.0, 110.0], [D0, D1, D2])
        assert AnalyticsService.calculate_twr(data, [D0, D1, D2], {}, {}) == [100.0, 100.0, 110.0]

    def test_single_point_fills_by_date_length(self):
        """采样点不足 2 个:按日期序列长度给基准占位,保证与 dates 下标对齐。"""
        assert AnalyticsService.calculate_twr(make_daily([100.0], [D0]), [D0, D1], {}, {}) == [100.0, 100.0]

    def test_empty_dates_returns_empty(self):
        assert AnalyticsService.calculate_twr([], [], {}, {}) == []


class TestMwrSeries:
    """每段百分比序列(起点 0)。"""

    def test_reports_segment_percentage(self):
        data = make_daily([1000.0, 1100.0, 1045.0], [D0, D1, D2])
        assert AnalyticsService._calculate_mwr(data, [D0, D1, D2], {}, {}) == [0.0, 10.0, -5.0]

    def test_shares_stripping_with_twr(self):
        """与 TWR 共用剥离:同一段得出的百分比应当一致(申购计期初 → −0.94%)。"""
        data = make_daily([11308.03, 14184.81], [D0, D1])
        assert AnalyticsService._calculate_mwr(data, [D0, D1], {D1: 3110.00}, {D0: 98.99}) == [0.0, -0.94]

    def test_uncomputable_segment_reports_zero(self):
        data = make_daily([0.0, 100.0], [D0, D1])
        assert AnalyticsService._calculate_mwr(data, [D0, D1], {}, {}) == [0.0, 0.0]


class _SnapshotRow:
    """快照行的最小替身(只用到这四个属性)。"""

    def __init__(self, snapshot_date: date, fund_code: str, shares: float, nav: float) -> None:
        self.snapshot_date = snapshot_date
        self.fund_code = fund_code
        self.shares = shares
        self.nav = nav


class TestRemovedValueGuard:
    """记录不完整(赎回份额 > 当日持有份额)时的保护:赎回调整以「组合实际被移走的市值」为上限。

    真实场景(2026-09-20):2023-01-04 两笔赎回回款 **116.73**,而组合当天实际只被移走 **66.61**
    (162605 卖 23.96 份、记录里只持有 4.99 份)→ 旧口径把差额 50.12 算成收益,曲线上出现假涨。
    """

    def test_capped_by_actual_removed_value(self):
        data = make_daily([780.57, 723.97], [D0, D1])
        pair = AnalyticsService.adjusted_pair(
            data, [D0, D1], {}, {D0: 116.73}, 1, removed_values={D0: 66.61}, gap_days={D0}
        )
        assert pair == (780.57 - 66.61, 723.97)  # 不再按回款 116.73 剥离开头
        assert segment_return(pair) > 0

    def test_nav_timing_difference_is_not_capped(self):
        """**关键回归**:不是缺口日(只是净值时点造成的 ~1% 差异)时不许截断,否则正常收益被削掉。

        这正是第一版实现的坑:按「回款 > 移走市值」判定会把 31 个正常日子也当成缺口。
        """
        data = make_daily([1000.0, 1100.0], [D0, D1])
        assert AnalyticsService.adjusted_pair(
            data, [D0, D1], {}, {D0: 100.0}, 1, removed_values={D0: 99.0}, gap_days=set()
        ) == (900.0, 1100.0)

    def test_consistent_data_keeps_old_behaviour(self):
        """数据一致(回款 = 实际移走市值)时,结果与旧口径逐字相同(含手续费的情形仍按回款)。"""
        data = make_daily([1000.0, 1100.0], [D0, D1])
        assert AnalyticsService.adjusted_pair(
            data, [D0, D1], {}, {D0: 100.0}, 1, removed_values={D0: 100.0}, gap_days={D0}
        ) == (900.0, 1100.0)

    def test_within_tolerance_is_not_capped(self):
        """即使命中缺口日,差额 ≤1 元(分位级)也不截断。"""
        data = make_daily([1000.0, 1100.0], [D0, D1])
        assert AnalyticsService.adjusted_pair(
            data, [D0, D1], {}, {D0: 100.5}, 1, removed_values={D0: 100.0}, gap_days={D0}
        ) == (899.5, 1100.0)

    def test_missing_key_in_partial_map_is_safe(self):
        """removed_values 缺该日(部分表)时不能退化成 0 把回款全截掉。"""
        data = make_daily([1000.0, 1100.0], [D0, D1])
        assert AnalyticsService.adjusted_pair(
            data, [D0, D1], {}, {D0: 100.0}, 1, removed_values={}, gap_days={D0}
        ) == (900.0, 1100.0)

    def test_realtime_path_without_snapshots_keeps_old_behaviour(self):
        """走实时兜底(无快照)时不传任何缺口信息 → 与旧口径一致。"""
        data = make_daily([1000.0, 1100.0], [D0, D1])
        assert AnalyticsService.adjusted_pair(data, [D0, D1], {}, {D0: 100.0}, 1) == (900.0, 1100.0)

    def test_twr_series_no_longer_inflates(self):
        """整段序列:缺口日不再把差额算成收益(旧 112.5 → 新 100.0)。"""
        data = make_daily([1000.0, 900.0, 1000.0], [D0, D1, D2])
        old = AnalyticsService.calculate_twr(data, [D0, D1, D2], {}, {D0: 200.0})
        new = AnalyticsService.calculate_twr(
            data, [D0, D1, D2], {}, {D0: 200.0}, removed_values={D0: 100.0}, gap_days={D0}
        )
        assert old[1] == 112.5  # 期初被多剥 100 → 虚假收益
        assert new[1] == 100.0  # 900/900 → 该段不产生收益
        assert abs(new[2] - 111.1111) < 0.01

    def test_mwr_uses_the_same_guard(self):
        """MWR 与 TWR 共用调整:同一段百分比一致。"""
        data = make_daily([1000.0, 900.0], [D0, D1])
        assert AnalyticsService._calculate_mwr(
            data, [D0, D1], {}, {D0: 200.0}, removed_values={D0: 100.0}, gap_days={D0}
        ) == [0.0, 0.0]

    def test_quality_payload(self):
        payload = AnalyticsService.data_quality_payload({D1: ['162605', '161725'], D0: ['162605']})
        assert payload['incompleteDates'] == [D0.isoformat(), D1.isoformat()]
        assert payload['funds'] == ['161725', '162605']
        assert '不完整' in payload['note']
        empty = AnalyticsService.data_quality_payload({})
        assert empty['incompleteDates'] == [] and empty['funds'] == []


class TestRemovedValueByDate:
    """按日「实际移走市值」的推导:份额在次一快照日才消失 → 归到赎回当日、按当日净值计价。"""

    def test_attributed_to_redemption_day_with_that_days_nav(self):
        snapshots = [
            _SnapshotRow(D0, '162605', 4.99, 2.559),  # D0 还持有
            _SnapshotRow(D0, '其它基金', 10.0, 1.0),
            _SnapshotRow(D1, '其它基金', 10.0, 1.0),  # D1 起 162605 没有行了(份额已清)
        ]
        removed, funds = _removed_value_by_date(snapshots)
        assert round(removed[D0], 4) == round(4.99 * 2.559, 4)
        assert funds[D0] == ['162605']
        assert D1 not in removed

    def test_no_change_means_no_removal(self):
        snapshots = [_SnapshotRow(D0, '000001', 5.0, 1.0), _SnapshotRow(D1, '000001', 5.0, 1.2)]
        removed, funds = _removed_value_by_date(snapshots)
        assert removed == {} and funds == {}


class TestOversellDetection:
    """缺口日的判据必须是「份额」而不是「金额」:金额口径会把净值时点差异误判成缺口。"""

    def test_flags_only_the_oversold_day(self):
        snapshots = [
            _SnapshotRow(D0, '162605', 4.99, 2.0),  # D0 只持有 4.99 份
            _SnapshotRow(D0, '502053', 9.58, 1.0),
            _SnapshotRow(D1, '502053', 0.0, 1.0),  # 502053 是正常赎清
        ]
        redemption_shares = {(D0, '162605'): 23.96, (D0, '502053'): 9.58}
        assert _oversell_days(snapshots, redemption_shares) == {D0: ['162605']}

    def test_nav_timing_only_day_is_not_flagged(self):
        """回款比快照市值大 1%(净值时点),但份额没超 → 不算缺口日。"""
        snapshots = [_SnapshotRow(D0, '502053', 9.58, 1.0), _SnapshotRow(D1, '502053', 0.0, 1.0)]
        assert _oversell_days(snapshots, {(D0, '502053'): 9.58}) == {}

    def test_day_without_snapshot_is_ignored(self):
        assert _oversell_days([], {(D0, '162605'): 10.0}) == {}
