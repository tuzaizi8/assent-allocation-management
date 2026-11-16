"""基金风险指标的纯函数单测(不需要 DB/Redis)。

只测 _returns_from_accum_nav:复权净值相邻相除生成日收益率的边界——
坏点(回源 NaN 落 0)跳过、空/单点序列返回空、收益率取值正确。
基准对齐与指标计算复用持仓版逻辑,由 test_risk_metrics.py 覆盖。
"""

from datetime import date

from module_portfolio.service.risk_metrics_service import RiskMetricsService


class TestReturnsFromAccumNav:
    def test_basic_daily_returns(self):
        pairs = [
            (date(2026, 1, 2), 1.0000),
            (date(2026, 1, 3), 1.0500),
            (date(2026, 1, 6), 0.9975),
        ]
        returns = RiskMetricsService._returns_from_accum_nav(pairs)
        assert [d for d, _ in returns] == [date(2026, 1, 3), date(2026, 1, 6)]
        assert abs(returns[0][1] - 0.05) < 1e-12
        assert abs(returns[1][1] - (0.9975 / 1.05 - 1)) < 1e-12

    def test_zero_nav_pair_skipped(self):
        """坏点(回源 NaN 落 0)两侧的相邻对都跳过,不产生除零/负净值收益。"""
        pairs = [
            (date(2026, 1, 2), 1.0),
            (date(2026, 1, 3), 0.0),
            (date(2026, 1, 6), 1.02),
        ]
        assert RiskMetricsService._returns_from_accum_nav(pairs) == []

    def test_empty_or_single_point_returns_empty(self):
        assert RiskMetricsService._returns_from_accum_nav([]) == []
        assert RiskMetricsService._returns_from_accum_nav([(date(2026, 1, 2), 1.0)]) == []
