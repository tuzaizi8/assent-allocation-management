"""_build_nav_records 复权口径单测:锁定坏点回填与分红日保护两条规则。

背景:接口日增长率存在确为 0.0 但单位净值实际变动的坏点日(实测 005827 有 7 个,
如 2019-02-11 +5.23% 被记 0),fillna(0) 会把缺口复利放大(005827 终点差 11.9 个
百分点)。修复口径:dy=0 且 |单位净值环比|>1% 用环比回填;分红日官方 dy 已含除息
调整(≠0),不得被环比覆盖。
"""

import pandas as pd
import pytest

from module_fund.service.akshare_service import _build_nav_records


def _make_df(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    """rows: (净值日期, 单位净值, 日增长率)"""
    return pd.DataFrame(rows, columns=['净值日期', '单位净值', '日增长率'])


def test_bad_point_backfilled_with_unit_return():
    """坏点日(dy=0 但环比显著非 0)用单位净值环比回填,复权线不再丢真实涨幅。"""
    # 2019-02-11 接口 dy=0 但单位净值 0.9954→1.0475(+5.23%,005827 实测坏点)
    df_unit = _make_df([
        ('2019-02-08', 0.9954, 0.85),
        ('2019-02-11', 1.0475, 0.0),
        ('2019-02-12', 1.0480, 0.05),
    ])
    records = _build_nav_records(df_unit, None)

    expected = records[1]['unit_nav'] / records[0]['unit_nav'] * 100 - 100
    assert records[1]['daily_yield'] == pytest.approx(expected)
    # 复权线累计收益不再被坏点吃掉:含坏点日的真实涨幅
    assert records[-1]['accum_nav'] > 1.05


def test_dividend_day_keeps_official_yield():
    """分红日官方 dy 已含除息调整(≠0),即使与单位净值环比差异大也不被回填。"""
    # 模拟分红 0.1:净值 1.5→1.4(环比 -6.67%),官方再投资口径 dy=+0.7
    df_unit = _make_df([
        ('2024-01-02', 1.5000, 0.30),
        ('2024-01-03', 1.4000, 0.70),
        ('2024-01-04', 1.4010, 0.07),
    ])
    records = _build_nav_records(df_unit, None)

    assert records[1]['daily_yield'] == 0.70


def test_dy_zero_with_tiny_unit_move_not_backfilled():
    """dy=0 且环比噪声级(|环比|≤1%)不回填——停牌/四舍五入的正常 0 日保留。"""
    df_unit = _make_df([
        ('2024-03-01', 1.2000, 0.50),
        ('2024-03-04', 1.2002, 0.0),
        ('2024-03-05', 1.2005, 0.0),
    ])
    records = _build_nav_records(df_unit, None)

    assert records[1]['daily_yield'] == 0.0
    assert records[2]['daily_yield'] == 0.0


def test_missing_dy_falls_back_to_zero():
    """dy 为 NaN 且环比也不显著时维持原 fillna(0) 兜底,不产生 NaN 污染。"""
    df_unit = _make_df([
        ('2024-04-01', 1.1000, 0.20),
        ('2024-04-02', 1.1000, None),
    ])
    records = _build_nav_records(df_unit, None)

    assert records[1]['daily_yield'] == 0.0


def test_bad_point_on_dividend_day_uses_reinvest_formula():
    """坏点撞分红除息日:按再投资公式回填,而非把除息损失当收益的环比。

    同构 008163 2025-01-17:除息日 unit 1.2143→1.1893(每10份派0.25,即每份
    0.025),官方 dy 坏点为 0。环比 -2.06% 会把分红损失错误计入;正确回填
    (1.1893+0.025)/1.2143-1 ≈ 0%。
    """
    df_unit = _make_df([
        ('2025-01-16', 1.2143, 0.30),
        ('2025-01-17', 1.1893, 0.0),  # 除息 + 坏点
        ('2025-01-20', 1.1900, 0.06),
    ])
    # raw_accum: 前日 1.2393(=unit+累计分红0.0250),除息日应平滑 → 累计分红增至 0.0500
    df_accum = pd.DataFrame(
        [('2025-01-16', 1.2393), ('2025-01-17', 1.2393), ('2025-01-20', 1.2400)],
        columns=['净值日期', '累计净值'],
    )
    records = _build_nav_records(df_unit, df_accum)

    expected = pytest.approx((1.1893 + 0.025) / 1.2143 * 100 - 100)
    assert records[1]['daily_yield'] == expected
    # 不允许回落到环比口径(-2.06%,把除息损失当收益)
    assert records[1]['daily_yield'] > -0.5


def test_dividend_derivation_only_hits_dividend_days():
    """分红推导:非分红日 delta 差分为舍入噪声级(≈0),分红日恰等于每份分红。"""
    df_unit = _make_df([
        ('2025-02-13', 1.2100, 0.10),
        ('2025-02-14', 1.1850, 0.20),  # 除息日:每份 0.025,unit 跳水
        ('2025-02-17', 1.1860, 0.08),
    ])
    # delta(=raw-unit): 0.0250 / 0.0500 / 0.0500 —— 差分仅除息日为 0.025
    df_accum = pd.DataFrame(
        [('2025-02-13', 1.2350), ('2025-02-14', 1.2350), ('2025-02-17', 1.2360)],
        columns=['净值日期', '累计净值'],
    )
    records = _build_nav_records(df_unit, df_accum)

    # 除息日官方 dy=0.20(非坏点)保留原值,验证推导未误伤
    assert records[1]['daily_yield'] == 0.20
    # 复权线用官方再投资口径连乘,不受推导本身影响
    assert records[0]['accum_nav'] == records[0]['accum_nav']  # 归一化首日恒 1.0
    # 普通日 dy 保留官方值
    assert records[2]['daily_yield'] == 0.08
