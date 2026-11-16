"""货币基金处理链单测:识别规则、七日年化解析、场内降级合理性校验。

背景(2026-10-08 事故):货币基金没有 Data_netWorthTrend,场外接口必失败后
降级场内接口——它对场外代码不报错而是把万份收益序列错位成单位净值返回,
被当真净值入库后买入份额、复权曲线全部失真。
"""

import inspect
from datetime import date

import pandas as pd
import pytest

from module_fund.service.akshare_service import (
    AkshareService,
    _build_money_nav_series,
    _build_nav_records,
    _fetch_money_yield_records,
)
from module_portfolio.service.position_calc_util import (
    MoneyAccumCurve,
    fund_realized_profit,
    money_market_value_on,
)
from module_portfolio.service.position_service import PositionService

SAMPLE_JS = (
    'var Data_sevenDaysYearIncome = [[1382630400000,0],[1382889600000,4.585],'
    '[1382976000000,5.29],[1720000000000,0.904]];'
    'var Data_millionCopiesIncome = [[1382630400000,1.3999],[1382889600000,1.3992]];'
)


class TestMoneyFundType:
    def test_money_keyword_detected(self):
        assert AkshareService.is_money_fund_type('货币型-普通货币') is True
        assert AkshareService.is_money_fund_type('货币型-理财型') is True

    def test_non_money_and_empty(self):
        assert AkshareService.is_money_fund_type('混合型-偏股') is False
        assert AkshareService.is_money_fund_type(None) is False
        assert AkshareService.is_money_fund_type('') is False


class TestMoneyYieldParsing:
    def test_parse_seven_days_series(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self):
                return None

            text = SAMPLE_JS

        monkeypatch.setattr(
            'module_fund.service.akshare_service.requests.get',
            lambda *a, **k: FakeResp(),
        )
        records = _fetch_money_yield_records('000389')
        # 首日占位 0 被过滤,只留有效点;万份收益按日期对齐,缺日补 0
        assert len(records) == 3
        assert records[0]['nav_date'] == '2013-10-28'
        assert records[0]['annualized_7d'] == pytest.approx(4.585)
        assert records[0]['per_10k_income'] == pytest.approx(1.3992)
        assert records[-1]['annualized_7d'] == pytest.approx(0.904)
        # 样本里 2024-07-03 无对应万份收益点
        assert records[-1]['per_10k_income'] == 0.0
        assert records[1]['per_10k_income'] == 0.0

    def test_missing_variable_returns_empty(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self):
                return None

            text = 'var Data_assetAllocation = [];'

        monkeypatch.setattr(
            'module_fund.service.akshare_service.requests.get',
            lambda *a, **k: FakeResp(),
        )
        assert _fetch_money_yield_records('000389') == []


class TestMoneyNavSeries:
    def test_unit_nav_constant_and_accum_compounds(self):
        money = [
            {'nav_date': '2026-10-07', 'annualized_7d': 0.904, 'per_10k_income': 0.2464},
            {'nav_date': '2026-10-08', 'annualized_7d': 0.906, 'per_10k_income': 0.2464},
        ]
        records = _build_money_nav_series(money)
        # 单位净值恒 1.0:市值=份额,这是货币基金的本质
        assert all(r['unit_nav'] == 1.0 for r in records)
        # 万份收益 0.2464 元 → 日收益率 0.2464/10000
        expected = 1 * (1 + 0.2464 / 10000) ** 2
        assert records[-1]['accum_nav'] == pytest.approx(expected, abs=1e-6)
        # 日增长率单位与普通基金一致(%):0.2464/100
        assert records[0]['daily_yield'] == pytest.approx(0.2464 / 100)

    def test_zero_income_days_do_not_break_series(self):
        records = _build_money_nav_series([
            {'nav_date': '2026-10-07', 'annualized_7d': 0.9, 'per_10k_income': 0},
            {'nav_date': '2026-10-08', 'annualized_7d': 0.9, 'per_10k_income': 0.5},
        ])
        assert records[0]['accum_nav'] == pytest.approx(1.0, abs=1e-9)
        assert records[1]['accum_nav'] == pytest.approx(1 + 0.5 / 10000, abs=1e-9)

    def test_empty_money_records(self):
        assert _build_money_nav_series([]) == []


class TestEtfFallbackSanity:
    def test_absurd_accum_nav_rejected(self, monkeypatch):
        """场内降级拿到错位数据(accum_nav 连乘爆表)必须丢弃而非入库。"""
        garbage_unit = pd.DataFrame(
            {'净值日期': ['2026-10-07'], '单位净值': [0.2464], '日增长率': [0.0]}
        )
        garbage_accum = pd.DataFrame({'净值日期': ['2026-10-07'], '累计净值': [1.2e68]})
        monkeypatch.setattr(
            'module_fund.service.akshare_service.ak.fund_open_fund_info_em',
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Data_netWorthTrend is not defined')),
        )
        monkeypatch.setattr(
            'module_fund.service.akshare_service._fetch_etf_nav_df',
            lambda fund_code: (garbage_unit, garbage_accum),
        )
        from module_fund.service.akshare_service import _fetch_nav_records

        assert _fetch_nav_records('000389') == []

    def test_plausible_etf_data_accepted(self, monkeypatch):
        unit = pd.DataFrame(
            {'净值日期': ['2026-10-07'], '单位净值': [3.21], '日增长率': [0.31]}
        )
        accum = pd.DataFrame({'净值日期': ['2026-10-07'], '累计净值': [3.55]})
        monkeypatch.setattr(
            'module_fund.service.akshare_service.ak.fund_open_fund_info_em',
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('fail')),
        )
        monkeypatch.setattr(
            'module_fund.service.akshare_service._fetch_etf_nav_df',
            lambda fund_code: (unit, accum),
        )
        from module_fund.service.akshare_service import _fetch_nav_records

        records = _fetch_nav_records('000389')
        assert len(records) == 1
        assert records[0]['unit_nav'] == pytest.approx(3.21)


class TestMoneyMarketValue:
    """持有收益与真实基金收益匹配的核心:每笔交易从成交日起复利折算。"""

    @staticmethod
    def _curve():
        return MoneyAccumCurve([
            {'nav_date': '2026-10-01', 'accum_nav': 1.0},
            {'nav_date': '2026-10-02', 'accum_nav': 1.00005},
            {'nav_date': '2026-10-07', 'accum_nav': 1.00010},
        ])

    def test_compounds_from_own_purchase_date(self):
        curve = self._curve()
        # 10-01 买入:吃到 10-01 之后全部收益
        mv = money_market_value_on([(date(2026, 10, 1), 350)], [], curve, date(2026, 10, 8))
        assert mv == pytest.approx(350 * 1.00010)
        # 10-07 买入:此前收益不归它,市值仍是本金
        mv2 = money_market_value_on([(date(2026, 10, 7), 350)], [], curve, date(2026, 10, 8))
        assert mv2 == pytest.approx(350.0)

    def test_redemption_removes_future_growth(self):
        curve = self._curve()
        pairs = [(date(2026, 10, 1), 350)]
        # FIFO:赎回 175 从 10-01 锚(accum=1.0)移出,剩余 175 同锚复利
        redeemed = money_market_value_on(pairs, [(date(2026, 10, 2), 175)], curve, date(2026, 10, 8))
        expected = 175 * 1.00010
        assert redeemed == pytest.approx(expected)

    def test_redemption_day_still_held(self):
        """回归:赎回当日的市值必须包含被赎回份额(市值族口径)——此前赎回当天
        就扣除,700 份全赎当日 mv 骤降为残余收益 1.147,单日 −99.8%。"""
        curve = self._curve()
        pairs = [(date(2026, 10, 1), 700)]
        reds = [(date(2026, 10, 7), 700)]
        # 赎回当日:仍按全部份额复利计值
        mv_day = money_market_value_on(pairs, reds, curve, date(2026, 10, 7))
        assert mv_day == pytest.approx(700 * 1.00010)
        # 次日:被赎回份额连同其未来增值一并移出;FIFO 继承买入锚(1.0),
        # 全额移出后归零——旧公式的 0.07 残差正是幻影收益本身(2026-10-08 修正)
        mv_next = money_market_value_on(pairs, reds, curve, date(2026, 10, 8))
        assert mv_next == pytest.approx(0.0)

    def test_no_phantom_before_purchase_date(self):
        """回归:未来买入的份额不得提前出现在市值里——2021-12-09 的买入曾在
        2021-11-16 的快照里贡献 349.5 幻影,被 TWR 当成收益(曲线暴涨/暴跌)。"""
        curve = self._curve()
        # 单笔:成交日之前市值为 0
        assert money_market_value_on([(date(2026, 10, 7), 350)], [], curve, date(2026, 10, 1)) == 0.0
        # 两笔:第二笔(10-07)在 10-02 不贡献市值,只有第一笔复利
        pairs = [(date(2026, 10, 1), 350), (date(2026, 10, 7), 350)]
        mv = money_market_value_on(pairs, [], curve, date(2026, 10, 2))
        assert mv == pytest.approx(350 * 1.00005)

    def test_empty_curve_degrades_to_principal(self):
        mv = money_market_value_on([(date(2026, 10, 1), 350)], [], MoneyAccumCurve([]), date(2026, 10, 8))
        assert mv == pytest.approx(350.0)

    def test_daily_profit_is_value_diff(self):
        curve = self._curve()
        pairs = [(date(2026, 10, 1), 350)]
        latest, prev = curve.nth_dates(0)
        assert (latest, prev) == ('2026-10-07', '2026-10-02')
        profit = (
            money_market_value_on(pairs, [], curve, date.fromisoformat(latest))
            - money_market_value_on(pairs, [], curve, date.fromisoformat(prev))
        )
        assert profit == pytest.approx(350 * (1.00010 - 1.00005))


class TestMoneyRealizedProfit:
    """已实现盈亏:货基赎回的到账含每日结转收益,名义单价(恒 1.0)会把它吞成 0。"""

    @staticmethod
    def _rec(shares: float, amount: float | None, nav: float = 1.0):
        class R:
            pass

        r = R()
        r.shares = shares
        r.amount = amount
        r.nav_price = nav
        r.position_id = 1
        r.redemption_date = date(2026, 10, 7)
        return r

    @staticmethod
    def _buy(shares: float, amount: float):
        class P:
            pass

        p = P()
        p.shares = shares
        p.amount = amount
        p.position_id = 1
        p.purchase_date = date(2026, 10, 1)
        return p

    def test_money_realized_profit_via_amount_price(self):
        # 买 700 元(700 份),赎 700 份到账 701.15(结转收益)→ 已实现 1.15
        purchases = [self._buy(700.0, 700.0)]
        redemptions = [self._rec(700.0, 701.15)]
        realized = fund_realized_profit(
            purchases, redemptions, redeem_price_of=lambda r: r.amount / r.shares
        )
        assert realized == pytest.approx(1.15)

    def test_money_realized_profit_default_swallows_income(self):
        # 默认回调(nav_price=1.0)正是修复前的错误行为:已实现盈亏恒 0——钉住对照
        purchases = [self._buy(700.0, 700.0)]
        redemptions = [self._rec(700.0, 701.15)]
        assert fund_realized_profit(purchases, redemptions) == pytest.approx(0.0)

    def test_regular_fund_default_unchanged(self):
        # 普通基金不传回调:沿用 nav_price,行为不变(此前锁定口径)
        purchases = [self._buy(100.0, 100.0)]
        redemptions = [self._rec(100.0, None, nav=1.1)]
        assert fund_realized_profit(purchases, redemptions) == pytest.approx(10.0)


class TestGuardDecoratorRegression:
    """回归:插入 _guard_duplicate_submission 时把 create_position_services 原有的
    @classmethod 挤到了它头上,cls 被当首参传入导致线上 TypeError(2026-10-08)。
    装饰器叠错在 import 期不报错,ruff/tsc 均不拦,只能用反射钉住。"""

    def test_guard_is_plain_staticmethod(self):
        assert isinstance(
            inspect.getattr_static(PositionService, '_guard_duplicate_submission'),
            staticmethod,
        )

    def test_guard_takes_exactly_six_params(self):
        params = inspect.signature(
            inspect.getattr_static(PositionService, '_guard_duplicate_submission')
        ).parameters
        assert len(params) == 6

    def test_create_position_still_classmethod(self):
        assert isinstance(
            inspect.getattr_static(PositionService, 'create_position_services'),
            classmethod,
        )


class TestBuildNavRecordsContract:
    def test_records_shape(self):
        unit = pd.DataFrame(
            {'净值日期': ['2026-10-07'], '单位净值': [1.0], '日增长率': [0.0]}
        )
        accum = pd.DataFrame({'净值日期': ['2026-10-07'], '累计净值': [1.0]})
        records = _build_nav_records(unit, accum)
        assert records[0]['nav_date'] == '2026-10-07'
        assert records[0]['unit_nav'] == pytest.approx(1.0)
