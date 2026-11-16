"""逐基金日收益双档(_calc_daily_fund_profit)口径单测。

对齐用户给出的现实规则:净值 T+1 发布后,「昨日」(上一净值日)与
「今日」(最新净值日)两档收益必须并列可见,互不覆盖;今日买入不计入今日收益。
纯函数直接测,无需 mock(样板对齐 test_chart_period.py)。
"""

from module_portfolio.service.analytics_service import _calc_daily_fund_profit


def make_navs(rows: list[tuple[str, float]]) -> list[dict]:
    return [{'nav_date': d, 'unit_nav': v} for d, v in rows]


class TestLatestOffset:
    """offset=0:最新净值日(今日档)。"""

    def test_basic_profit(self):
        navs = make_navs([('2026-09-07', 1.0), ('2026-09-08', 1.1)])
        row = _calc_daily_fund_profit(navs, [('2026-09-06', 100.0)], [], 0)
        assert row['dailyProfit'] == 10.0
        assert row['navDate'] == '2026-09-08'
        assert row['prevNavDate'] == '2026-09-07'
        assert row['shares'] == 100.0

    def test_today_buy_excluded(self):
        """今日(最新净值日)买入的份额不计入今日收益:份额按前一净值日末算。"""
        navs = make_navs([('2026-09-07', 1.0), ('2026-09-08', 1.1)])
        # 100 份 9/6 前持有,9/8(今日)又买 100 份 → 今日收益只按 100 份算
        row = _calc_daily_fund_profit(
            navs, [('2026-09-06', 100.0), ('2026-09-08', 100.0)], [], 0
        )
        assert row['shares'] == 100.0
        assert row['dailyProfit'] == 10.0

    def test_no_holding_at_prev_nav_day(self):
        """前一净值日末未持有(建仓首日算昨日档)→ None,不进该档。"""
        navs = make_navs([('2026-09-07', 1.0), ('2026-09-08', 1.1)])
        row = _calc_daily_fund_profit(navs, [('2026-09-08', 100.0)], [], 0)
        assert row is None


class TestPrevOffset:
    """offset=1:上一净值日(昨日档),与最新档并列、互不覆盖。"""

    def test_prev_profit_stays_visible_after_nav_update(self):
        """核心回归:9/8 净值发布后,9/7(上一净值日)的收益仍可算出。"""
        navs = make_navs([
            ('2026-09-05', 1.0),
            ('2026-09-07', 1.2),
            ('2026-09-08', 1.1),
        ])
        # 9/7 收益 = 100 份 × (1.2 − 1.0) = 20,今日(9/8)收益 = −10
        prev = _calc_daily_fund_profit(navs, [('2026-09-04', 100.0)], [], 1)
        latest = _calc_daily_fund_profit(navs, [('2026-09-04', 100.0)], [], 0)
        assert prev['dailyProfit'] == 20.0
        assert prev['navDate'] == '2026-09-07'
        assert latest['dailyProfit'] == -10.0

    def test_prev_needs_three_nav_days(self):
        """净值不足 3 条时昨日档不存在(还凑不出上一净值日的前一日)。"""
        navs = make_navs([('2026-09-07', 1.0), ('2026-09-08', 1.1)])
        assert _calc_daily_fund_profit(navs, [('2026-09-06', 100.0)], [], 1) is None

    def test_redemption_excluded_from_prev_day_shares(self):
        """赎回 ≤ 前一净值日的份额从基数扣除;赎回当日(前一净值日之后)不扣。"""
        navs = make_navs([
            ('2026-09-05', 1.0),
            ('2026-09-07', 1.2),
            ('2026-09-08', 1.1),
        ])
        # 赎回 09-05(≤ 前一净值日)→ 09-07 档基数扣成 100 份
        row = _calc_daily_fund_profit(
            navs, [('2026-09-04', 200.0)], [('2026-09-05', 100.0)], 1
        )
        assert row['shares'] == 100.0
        assert row['dailyProfit'] == 20.0

    def test_redemption_after_prev_nav_day_keeps_fluctuating(self):
        """赎回发生在前一净值日之后(当日)→ 该档基数不扣,仍参与波动。"""
        navs = make_navs([
            ('2026-09-05', 1.0),
            ('2026-09-07', 1.2),
            ('2026-09-08', 1.1),
        ])
        # 赎回 09-06(> 前一净值日 09-05)→ 09-07 档基数仍 200 份
        row = _calc_daily_fund_profit(
            navs, [('2026-09-04', 200.0)], [('2026-09-06', 100.0)], 1
        )
        assert row['shares'] == 200.0
        assert row['dailyProfit'] == 40.0


class TestEdgeCases:
    def test_empty_nav_records(self):
        assert _calc_daily_fund_profit([], [], [], 0) is None

    def test_single_nav_day(self):
        navs = make_navs([('2026-09-08', 1.1)])
        assert _calc_daily_fund_profit(navs, [('2026-09-07', 100.0)], [], 0) is None

    def test_rounding(self):
        """四位小数舍入:份额×净值差的长尾不裸奔到前端。"""
        navs = make_navs([('2026-09-07', 1.0), ('2026-09-08', 1.10001)])
        row = _calc_daily_fund_profit(navs, [('2026-09-06', 333.333)], [], 0)
        assert row['dailyProfit'] == round(333.333 * 0.10001, 4)
