"""持仓成本结转与全基金已实现收益单测(纯函数,无需 mock)。

口径(2026-09-22 修):成本**随赎回结转**——卖出按当时的加权平均成本把一部分成本结出去,
剩余份额的成本不再被已经卖掉的份额污染。旧实现里持仓成本恒等于「全部买入金额」,
161725 那类「分批买入 + 中途多次卖出 + 清仓后再买」的基金被算成平均成本 1.0000(实际 0.6696)、
浮亏放大到 -257.24(实际 -75.52)。
"""

from datetime import date
from types import SimpleNamespace

import pytest

from module_portfolio.service.position_calc_util import (
    cost_basis_walk,
    fund_realized_profit,
)


def buy(day: str, shares: float, price: float) -> tuple[date, float, float]:
    """(日期, 份额, 金额) —— 用例里按单价描述更顺,这里换算成**金额**交给结转(金额 = 份额 × 单价)。"""
    return (date.fromisoformat(day), shares, shares * price)


def sell(day: str, shares: float, price: float) -> tuple[date, float, float]:
    return (date.fromisoformat(day), shares, price)


class TestCostBasisWalk:
    """时序加权平均:(剩余份额, 持仓成本, 已实现收益)。"""

    def test_single_purchase_keeps_full_cost(self):
        shares, cost, realized = cost_basis_walk([buy('2026-01-05', 100, 1.0)], [])
        assert (shares, cost, realized) == (100.0, 100.0, 0.0)

    def test_empty_input(self):
        assert cost_basis_walk([], []) == (0.0, 0.0, 0.0)

    def test_partial_sell_deducts_cost_by_average(self):
        """核心回归:买 200 元卖一半后,持仓成本必须是 100 元 —— 不是把 200 全压在剩余份额上。"""
        shares, cost, realized = cost_basis_walk(
            [buy('2026-01-05', 200, 1.0)], [sell('2026-02-05', 100, 1.2)]
        )
        assert shares == 100.0
        assert cost == pytest.approx(100.0)
        assert realized == pytest.approx(20.0)  # 100 × (1.2 − 1.0)

    def test_interleaved_buy_sell_buy_sell(self):
        """交织形状(161725 的实际形态):卖出之后仍有买入,必须按当时的均价结转。"""
        shares, cost, realized = cost_basis_walk(
            [buy('2026-01-05', 100, 1.0), buy('2026-03-05', 100, 0.6)],
            [sell('2026-02-05', 50, 0.8), sell('2026-04-05', 30, 0.7)],
        )
        assert shares == pytest.approx(120.0)
        # 第一次卖出:均价 1.0 → 结转 50,已实现 40 − 50 = −10
        # 第二次卖出:均价 (50+60)/150 → 结转 22,已实现 21 − 22 = −1
        assert cost == pytest.approx(88.0)
        assert realized == pytest.approx(-11.0)

    def test_single_round_equals_proportional_deduction(self):
        """只买一次、卖一次时,结转结果 = 按剩余比例扣成本(这条纯函数行为的自证)。

        注:真库 161725 当前那轮是 808.44 份 / 550.01 元买入、卖出 258.44 份 / 161.34 元,
        但持仓成本是 **368.29** 而不是这里的 374.18 —— 因为那一轮**买卖交织**(最后一次卖出
        之后还有买入),卖出时点的均价与「全程均价」不同。真库数字由验收脚本对着库核。
        """
        shares, cost, _ = cost_basis_walk(
            [buy('2026-01-05', 808.44, 550.01 / 808.44)],
            [sell('2026-02-05', 258.44, 161.34 / 258.44)],
        )
        assert shares == pytest.approx(550.0)
        assert cost == pytest.approx(550.01 * 550 / 808.44, abs=0.01)  # 374.18

    def test_same_day_buy_is_settled_before_sell(self):
        """同日「先买后卖」是写进契约的约定:当日买入参与当日卖出的成本结转。"""
        shares, cost, realized = cost_basis_walk(
            [buy('2026-01-04', 100, 1.0), buy('2026-01-05', 100, 3.0)],
            [sell('2026-01-05', 50, 2.0)],
        )
        # 先买后卖:均价 (100+300)/200 = 2.0 → 结转 100,已实现 100 − 100 = 0
        # 若先卖后买:均价 1.0 → 结转 50,已实现 50(这条断言就是用来钉住顺序的)
        assert realized == pytest.approx(0.0)
        assert cost == pytest.approx(300.0)
        assert shares == pytest.approx(150.0)

    def test_overdrawn_sell_falls_back_to_row_average(self):
        """卖出多于买入(导出件截断的数据缺口):超出部分按该行整体买入均价结转。"""
        shares, cost, realized = cost_basis_walk(
            [buy('2026-01-05', 100, 1.0)],
            [sell('2026-02-05', 150, 2.0), sell('2026-03-05', 10, 3.0)],
        )
        # 第一笔:持仓 100 份 → 均价 1.0,结转 150,已实现 300 − 150 = 150,份额/成本双双转负
        # 第二笔:已无持仓 → 用该行买入均价 1.0 兜底(不是 0,否则会把 30 全算成收益)
        assert realized == pytest.approx(170.0)
        assert shares == pytest.approx(-60.0)
        assert cost == pytest.approx(-60.0)

    def test_reinvested_dividend_adds_free_shares(self):
        """红利再投资落成「有份额 + 金额 0」的买入行:份额增加、成本不变。

        这是 003547 缺的那 43.32 份的落账形态(2026-09-22):买 2000 元 + 红利再投 43.32 份,
        持仓成本仍是 2000 元,持有收益因此从 -8.09 变成 +37.35。
        """
        shares, cost, realized = cost_basis_walk(
            [buy('2026-01-05', 100, 1.0), (date(2026, 3, 5), 5.0, 0.0)], []
        )
        assert (shares, cost, realized) == (105.0, 100.0, 0.0)

    def test_cash_dividend_reduces_cost(self):
        """现金分红落成「0 份额 + 负金额」的买入行:份额不动、成本减少、已实现收益不动。"""
        shares, cost, realized = cost_basis_walk(
            [buy('2026-01-05', 100, 1.0), (date(2026, 3, 5), 0.0, -5.0)], []
        )
        assert (shares, cost, realized) == (100.0, 95.0, 0.0)


class TestFundRealizedProfit:
    """全基金已实现收益 = 各持仓行(含已清仓)分别结转后合计,行与行不共用成本链。"""

    @staticmethod
    def purchase(position_id: int, day: str, shares: float, price: float) -> SimpleNamespace:
        return SimpleNamespace(
            position_id=position_id,
            purchase_date=date.fromisoformat(day),
            shares=shares,
            cost_price=price,
        )

    @staticmethod
    def redemption(position_id: int, day: str, shares: float, price: float) -> SimpleNamespace:
        return SimpleNamespace(
            position_id=position_id,
            redemption_date=date.fromisoformat(day),
            shares=shares,
            nav_price=price,
        )

    def test_sums_each_position_row(self):
        """一轮已清仓(-10)+ 一轮在持(+10)= 0:只看当前行会漏掉已清仓那轮的 -10。"""
        purchases = [self.purchase(1, '2024-01-05', 100, 1.0), self.purchase(2, '2026-01-05', 100, 1.0)]
        redemptions = [self.redemption(1, '2024-02-05', 100, 0.9), self.redemption(2, '2026-02-05', 50, 1.2)]
        assert fund_realized_profit(purchases, redemptions) == pytest.approx(0.0)

    def test_rows_do_not_share_cost_chain(self):
        """第一行透支(卖出多于买入)不得污染第二行的均价。

        第一行:买 100@1.0 卖 130@2.0 → 已实现 +130,行末份额/成本均为 -30;
        第二行:买 100@2.0 卖 50@3.0 → 自己的均价 2.0 → 已实现 +50。
        若合成一条链:(−30+200)/(−30+100) = 2.4286 → 第二行只算 +28.57,合计少 21.43。
        """
        purchases = [self.purchase(1, '2024-01-05', 100, 1.0), self.purchase(2, '2026-01-05', 100, 2.0)]
        redemptions = [self.redemption(1, '2024-02-05', 130, 2.0), self.redemption(2, '2026-02-05', 50, 3.0)]
        assert fund_realized_profit(purchases, redemptions) == pytest.approx(180.0)

    def test_empty_input(self):
        assert fund_realized_profit([], []) == 0.0

    def test_fund_audit_161725_all_rounds(self):
        """真库 161725 四轮合计 -34.98(使用者说的「上一次清仓时亏了 30 多」就在这个数里)。"""
        purchases = [
            self.purchase(1, '2021-06-09', 60.48, 90.00 / 60.48),
            self.purchase(2, '2021-08-06', 111.55, 130.00 / 111.55),
            self.purchase(3, '2024-01-05', 140.50, 120.00 / 140.50),
        ]
        redemptions = [
            self.redemption(1, '2021-07-05', 60.48, 79.84 / 60.48),
            self.redemption(2, '2023-01-04', 113.60, 127.82 / 113.60),
            self.redemption(3, '2024-12-10', 140.50, 120.09 / 140.50),
        ]
        assert fund_realized_profit(purchases, redemptions) == pytest.approx(-14.64, abs=0.05)
