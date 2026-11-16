"""持仓风险指标单测:纯函数层(`_compute_metrics` 与两个 payload 组装),不连数据库。

QuantStats 0.0.81 已实测的行为(本文件断言依赖这些事实):
- `drawdown_details` 的输入是「回撤序列」(`to_drawdown_series` 的产物),不是收益率序列;
  「max drawdown」列是**百分数**(-16.09 = -16.09%);
- 无回撤 / 单点序列返回 0 行;全零收益下 sharpe 为 NaN(本 service 需降级为 None);
- `monthly_returns` 的 index 是年份(字符串)、列是 JAN..DEC + EOY,值为小数。
"""


from datetime import date

import numpy as np
import pandas as pd
import pytest

from module_fund.service.akshare_service import RISK_FREE_RATE_FALLBACK_ANNUAL, mean_yield_in_window
from module_portfolio.service.risk_metrics_service import RiskMetricsService


def _series(values: list[float], start: str = '2026-01-01') -> pd.Series:
    """工作日频率的收益率小数序列(带 DatetimeIndex,与 service 组装产物一致)。"""
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)))


def test_metrics_core_path():
    """构造「+10% → -20% → +30%」的收益路径:最大回撤恰为 -20%,且第三天修复。"""
    returns = _series([0.10, -0.20, 0.30])
    metrics = RiskMetricsService._compute_metrics(returns, benchmark=None)

    # 累计净值 1.10 → 0.88 → 1.144:最大回撤 = (0.88 - 1.10) / 1.10 = -20%
    assert metrics['maxDrawdown'] == pytest.approx(-20.0)
    assert metrics['maxDrawdownStart'] == '2026-01-02'
    assert metrics['maxDrawdownValley'] == '2026-01-02'
    # end = 该段最后一个水下日(01-05 已修复、dd 归 0);修复发生在其后第一个交易日
    assert metrics['maxDrawdownEnd'] == '2026-01-02'
    # 谷底(01-02)到修复日(01-05)隔 3 个自然日;days = 含首尾 1 天
    assert metrics['recoveryDays'] == 3
    assert metrics['longestDrawdownDays'] == 1
    # 年化波动率 = 样本标准差 × √252(百分数)
    expected_vol = float(np.std([0.10, -0.20, 0.30], ddof=1)) * np.sqrt(252) * 100
    assert metrics['annualVolatility'] == pytest.approx(expected_vol, abs=0.01)
    assert metrics['sharpe'] is not None
    assert metrics['sortino'] is not None
    assert metrics['calmar'] is not None
    assert metrics['downsideVolatility'] is not None
    assert metrics['winRate'] == pytest.approx(66.67)  # 3 天里 2 天为正
    assert metrics['var'] is not None
    assert metrics['cvar'] is not None
    # 基准缺失:基准侧四项全部降级为 None
    assert metrics['informationRatio'] is None
    assert metrics['beta'] is None
    assert metrics['alpha'] is None
    assert metrics['trackingError'] is None


def test_metrics_tracking_error_formula():
    """跟踪误差 = (组合 - 基准) 的样本标准差 × √252(QuantStats 没有该函数,手写口径)。"""
    returns = _series([0.01, -0.02, 0.03, 0.005])
    benchmark = _series([0.008, -0.01, 0.02, 0.004])
    metrics = RiskMetricsService._compute_metrics(returns, benchmark)

    diff = (returns - benchmark).std() * np.sqrt(252) * 100
    assert metrics['trackingError'] == pytest.approx(diff, abs=0.01)
    assert metrics['beta'] is not None
    assert metrics['alpha'] is not None
    assert metrics['informationRatio'] is not None


def test_metrics_no_drawdown():
    """全正收益:无回撤 ⇒ 回撤起止/修复天数/最长持续期全为空,最大回撤为 0。"""
    metrics = RiskMetricsService._compute_metrics(_series([0.01, 0.02, 0.005]), benchmark=None)

    assert metrics['maxDrawdown'] == 0.0
    assert metrics['maxDrawdownStart'] is None
    assert metrics['maxDrawdownValley'] is None
    assert metrics['maxDrawdownEnd'] is None
    assert metrics['recoveryDays'] is None
    assert metrics['longestDrawdownDays'] == 0


def test_metrics_all_zero_returns_degrade_to_none():
    """全零收益:sharpe 除零为 NaN ⇒ 降级 None,波动率/回撤为 0,不抛异常。"""
    metrics = RiskMetricsService._compute_metrics(_series([0.0, 0.0, 0.0]), benchmark=None)

    assert metrics['annualVolatility'] == 0.0
    assert metrics['maxDrawdown'] == 0.0
    assert metrics['sharpe'] is None
    assert metrics['winRate'] == 0.0


def test_metrics_single_point_does_not_raise():
    """单点序列:各统计量取不到也应安全降级,不抛异常。"""
    metrics = RiskMetricsService._compute_metrics(_series([0.01]), benchmark=None)

    assert metrics['maxDrawdown'] == 0.0
    assert metrics['longestDrawdownDays'] == 0
    assert metrics['sharpe'] is None or isinstance(metrics['sharpe'], float)


def test_drawdown_series_payload():
    """回撤序列 payload:日期为 ISO 字符串,值为负的百分数(两位小数)。"""
    returns = _series([0.10, -0.20, 0.30])
    payload = RiskMetricsService._drawdown_series_payload(returns)

    assert payload[0] == {'date': '2026-01-01', 'dd': 0.0}
    assert payload[1]['dd'] == pytest.approx(-20.0)
    assert payload[2]['dd'] == 0.0


def test_monthly_returns_payload():
    """月度收益 payload:每行 year + 12 个月 + 当年累计,缺数据月份为 None。"""
    returns = _series([0.10, -0.20, 0.30, 0.01, -0.01, 0.02], start='2026-02-02')
    payload = RiskMetricsService._monthly_returns_payload(returns)

    assert payload, '应至少有一个年份行'
    for row in payload:
        assert isinstance(row['year'], int)
        assert len(row['months']) == 12
        assert all(v is None or isinstance(v, float) for v in row['months'])
    # 月度值是**月内日收益复利合成**,不是单日值:2 月 = comp(0.10, -0.20, 0.30, 0.01, 0.99...按实际日)
    feb_days = [v for d, v in zip(returns.index, returns.values) if d.month == 2]
    expected_feb = (float(np.prod([1 + v for v in feb_days])) - 1) * 100
    feb_row = next(row for row in payload if row['year'] == 2026)
    assert feb_row['months'][1] == pytest.approx(expected_feb, abs=0.01)


def test_var_cvar_use_empirical_quantile():
    """VaR/CVaR 是**实测**(历史模拟)分位,不是 qs 的正态近似:标线左侧恰好是最差 5% 天。

    100 天里 10 天为负、5% 分位插值落在第 5~6 个负收益之间,故分位线左侧正好 5 天。
    """
    values = [-0.05, -0.045, -0.04, -0.035, -0.03, -0.025, -0.02, -0.015, -0.01, -0.005] + [0.01] * 90
    returns = _series(values)
    metrics = RiskMetricsService._compute_metrics(returns, benchmark=None)

    q05 = float(returns.quantile(0.05))
    assert (returns <= q05).sum() == 5, '分位线左侧应当正好是最差的 5% 天数'
    assert metrics['var'] == pytest.approx(round(q05 * 100, 2))
    assert metrics['cvar'] == pytest.approx(round(float(returns[returns <= q05].mean()) * 100, 2))


def test_mean_yield_in_window():
    """无风险利率 = 区间内国债收益率的算术平均(小数年化);区间无数据返回 None 以便降级。"""
    records = [
        {'date': '2025-12-31', 'yield': 2.0},
        {'date': '2026-01-02', 'yield': 1.0},
        {'date': '2026-06-30', 'yield': 3.0},
    ]
    assert mean_yield_in_window(records, date(2026, 1, 1), date(2026, 1, 31)) == pytest.approx(0.01)
    # 边界含首尾当日
    assert mean_yield_in_window(records, date(2026, 1, 2), date(2026, 6, 30)) == pytest.approx(0.02)
    assert mean_yield_in_window(records, date(2024, 1, 1), date(2024, 12, 31)) is None


def test_compute_metrics_reports_risk_free_rate():
    """传进去的 rf 要如实回报(百分数):前端夏普卡副文本靠它显示,不能写死 1.5%。"""
    returns = _series([0.01, 0.02, 0.03, 0.04, 0.05])
    assert RiskMetricsService._compute_metrics(returns, benchmark=None, rf=0.02)['riskFreeRate'] == pytest.approx(2.0)
    # 不传时用兜底常量(取数失败路径)
    fallback = RiskMetricsService._compute_metrics(returns, benchmark=None)['riskFreeRate']
    assert fallback == pytest.approx(RISK_FREE_RATE_FALLBACK_ANNUAL * 100)


# ===== 响应扩展:年化走势 / 滚动风险 / 直方图 / 胜负天数 =====

def test_annualized_series_constant_daily_return():
    """恒定日收益 r:第 n 天年化 = (1+r)^252 - 1(与 n 无关),前 20 天不画。"""
    r = 0.001
    n_days = 80
    returns = _series([r] * n_days)
    payload = RiskMetricsService._annualized_series_payload(returns)

    assert payload[0]['date'] == returns.index[20].strftime('%Y-%m-%d')
    assert len(payload) == n_days - 20
    expected = ((1 + r) ** 252 - 1) * 100
    assert all(p['value'] == pytest.approx(expected, abs=0.01) for p in payload)
    # 末点恒等式:年化走势末点 == 收益走势末点(累计收益率)按同一条序列年化的结果
    cum_end = float((1 + returns).prod())
    assert payload[-1]['value'] == pytest.approx((cum_end ** (252 / n_days) - 1) * 100, abs=0.01)


def test_rolling_series_shapes():
    """60 窗口:四条滚动序列长度 = 点数 − 59;组合波动率恒为正;基准缺失时基准两条为空。"""
    values = [0.01, -0.02, 0.03, 0.005, -0.01, 0.02] * 15  # 90 点
    returns = _series(values)
    bench = _series([0.005, 0.01, -0.005, 0.0, 0.008, -0.003] * 15)
    payload = RiskMetricsService._rolling_series_payload(returns, bench)

    expected_len = len(values) - 59
    assert len(payload['portfolioVol']) == expected_len
    assert len(payload['benchmarkVol']) == expected_len
    assert len(payload['sharpe']) == expected_len
    assert len(payload['benchmarkSharpe']) == expected_len
    assert all(p['value'] > 0 for p in payload['portfolioVol'])

    no_bench = RiskMetricsService._rolling_series_payload(returns, None)
    assert no_bench['benchmarkVol'] == []
    assert no_bench['benchmarkSharpe'] == []
    assert len(no_bench['sharpe']) == expected_len


def test_histogram_and_return_stats():
    """直方图 21 条边(20 bin)、counts 求和 = 交易日数;胜负平天数与序列一致。"""
    values = [0.01, -0.02, 0.03, 0.0, 0.005, -0.01] * 10  # 60 点,每周期 3 胜 2 负 1 平
    returns = _series(values)

    hist = RiskMetricsService._histogram_payload(returns)
    assert len(hist['binEdges']) == 21
    assert sum(hist['counts']) == 60

    stats = RiskMetricsService._return_stats(returns)
    assert stats == {'winDays': 30, 'loseDays': 20, 'flatDays': 10}


def test_return_series_payload_values_are_cumulative_returns():
    """累计收益率(%):日收益复利累乘(1.10 → 0.88 → 1.144),负号保留。"""
    payload = RiskMetricsService._return_series_payload(_series([0.10, -0.20, 0.30]))

    assert [p['value'] for p in payload] == [10.0, -12.0, 14.4]


def test_return_series_payload_shares_path_with_drawdown():
    """关键不变量:曲线自身的「距历史最高点的跌幅」必须等于 drawdownSeries。

    这是前端能把绿/红两段标注画在正确位置的前提——早期用 cum_by_date(TWR 全量日期链)
    组装时两条路径分叉,真库实测曲线上量出的最大回撤比 metrics.maxDrawdown 少 1.22
    个百分点,标注会偏。
    """
    returns = _series([0.10, -0.05, -0.20, 0.30, -0.02])
    payload = RiskMetricsService._return_series_payload(returns)
    drawdown_series = RiskMetricsService._drawdown_series_payload(returns)

    assert [p['date'] for p in payload] == [p['date'] for p in drawdown_series]

    peak = None
    for point, dd_point in zip(payload, drawdown_series):
        peak = point['value'] if peak is None else max(peak, point['value'])
        expected_dd = ((1 + point['value'] / 100) / (1 + peak / 100) - 1) * 100
        # 两者都保留 2 位小数,累计误差允许 0.05
        assert expected_dd == pytest.approx(dd_point['dd'], abs=0.05)
