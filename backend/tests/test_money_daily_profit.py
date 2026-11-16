"""货币基金日收益口径单测:市值差两端必须冻结在同一份「prev 收盘时点在场」的交易集合。

2026-11-04 实证:直接用各时点市值相减,prev 收盘在场、latest 前已赎回的份额在
latest 市值里已移出——赎回流出被当成当日亏损(赎回 400 份余额宝,「今日收益」
出现 ≈ −400 的幻影巨亏);窗口内买入的本金流入会被当成当日盈利。申赎是资金
进出不是盈亏,冻结边界与 shares 字段的日收益族口径(shares_held_at_close_pairs:
赎回 ≤ prev 扣除)逐字一致。
"""

from datetime import date

import pytest

from module_portfolio.service.analytics_service import _money_daily_fund_profit_row
from module_portfolio.service.position_calc_util import (
    MoneyAccumCurve,
    money_market_value_on,
)


def make_curve() -> MoneyAccumCurve:
    """4 根累计收益序列,每日每份结转 0.001(accum 1.000 → 1.003)。"""
    return MoneyAccumCurve(
        [
            {'nav_date': '2026-01-01', 'accum_nav': 1.0},
            {'nav_date': '2026-01-02', 'accum_nav': 1.001},
            {'nav_date': '2026-01-03', 'accum_nav': 1.002},
            {'nav_date': '2026-01-04', 'accum_nav': 1.003},
        ]
    )


def test_full_redemption_on_prev_day_returns_none_not_loss():
    """prev 当日全额赎回:份额归 0 → 不进该档(返回 None),绝不输出巨亏行。

    修复前此处返回 shares=0 但 dailyProfit=−400.8 的行(赎回流出被记成巨亏),
    对应实证:赎回 400 份余额宝次日「今日收益」出现 ≈ −400。
    """
    row = _money_daily_fund_profit_row(
        make_curve(),
        [('2026-01-01', 400.0)],
        [('2026-01-03', 400.0)],
        offset=0,
    )
    assert row is None


def test_partial_redemption_on_prev_day_only_earns_for_surviving_lots():
    """prev 当日部分赎回:仅在场份额计收益,被赎 400 份既不亏也不赚。"""
    row = _money_daily_fund_profit_row(
        make_curve(),
        [('2026-01-01', 400.0), ('2026-01-02', 100.0)],
        [('2026-01-03', 400.0)],
        offset=0,
    )
    assert row is not None
    assert row['shares'] == pytest.approx(100.0)
    expected = (
        400.0 * (1.003 - 1.002)
        + 100.0 * (1.003 / 1.001 - 1.002 / 1.001)
    )
    assert row['dailyProfit'] == pytest.approx(expected, abs=1e-9)


def test_purchase_on_latest_not_counted_as_profit():
    """latest 当日买入的份额不在 prev 收盘在场集合:本金不虚增当日收益。

    修复前此处得到 0.4 + 400×1.003 ≈ 401.6(新买入本金被当成收益)。
    """
    row = _money_daily_fund_profit_row(
        make_curve(),
        [('2026-01-01', 400.0), ('2026-01-04', 400.0)],
        [],
        offset=0,
    )
    assert row is not None
    assert row['shares'] == pytest.approx(400.0)
    assert row['dailyProfit'] == pytest.approx(0.4, abs=1e-9)


def test_redemption_on_latest_still_held_and_earns():
    """赎回日=latest 档:份额仍在 prev 收盘在场集合,照常享受窗口收益(T+1)。"""
    row = _money_daily_fund_profit_row(
        make_curve(),
        [('2026-01-01', 400.0)],
        [('2026-01-04', 400.0)],
        offset=0,
    )
    assert row is not None
    assert row['shares'] == pytest.approx(400.0)
    assert row['dailyProfit'] == pytest.approx(0.4, abs=1e-9)


def test_hold_only_window_matches_raw_market_value_diff():
    """无申赎的持有段:冻结口径与裸市值差一致(回归保障,行为不变)。"""
    curve = make_curve()
    buys = [(date.fromisoformat('2026-01-01'), 400.0)]
    row = _money_daily_fund_profit_row(curve, [('2026-01-01', 400.0)], [], offset=0)
    raw_diff = money_market_value_on(
        buys, [], curve, date.fromisoformat('2026-01-04')
    ) - money_market_value_on(buys, [], curve, date.fromisoformat('2026-01-03'))
    assert row is not None
    assert row['dailyProfit'] == pytest.approx(raw_diff, abs=1e-9)
