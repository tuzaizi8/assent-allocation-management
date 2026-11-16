"""快照现金流口径单测:净投入按「实际收付金额」算,不是按「份额 × 单价」推算。

2026-09-22 改:此前买入侧用 `份额×成本价`、赎回侧用 `份额×净值`,两个后果——
① **现金分红行**(份额 0、金额 -17.56)推算恒为 0,分红回收被整段漏掉(快照累计盈亏少报 30.88);
② 赎回用毛额(未扣赎回费),把赎回费算成了收入。
改后两侧都「金额优先、缺失回退份额价」,老数据(amount 未落库)仍可兜底。
"""

from datetime import date

from module_portfolio.service.position_calc_util import (
    purchase_amount,
    redemption_amount,
)
from module_portfolio.service.snapshot_service import SnapshotService


class Record:
    """买入/赎回记录的替身:只带两个助手会读的字段。"""

    def __init__(self, *, shares: float, price: float, amount: float | None):
        self.shares = shares
        self.cost_price = price
        self.nav_price = price
        self.amount = amount


def flow_rows(transactions: list[dict], start: date, end: date) -> list[dict]:
    return SnapshotService._build_cash_flow_rows(1, transactions, start, end)


# ===== 两个取数助手(快照两侧共用) =====


def test_purchase_amount_prefers_stored_amount():
    """买入:落库确认金额优先(含申购费),缺失才回退份额×成本价。"""
    assert purchase_amount(Record(shares=10, price=1.0, amount=9.99)) == 9.99
    assert purchase_amount(Record(shares=10, price=1.0, amount=None)) == 10.0


def test_redemption_amount_prefers_stored_amount():
    """赎回:确认金额 = 实际到账(已扣赎回费);缺失回退份额×净值(毛额)。"""
    assert redemption_amount(Record(shares=10, price=1.2, amount=11.94)) == 11.94
    assert redemption_amount(Record(shares=10, price=1.2, amount=None)) == 12.0


def test_cash_dividend_row_contributes_its_negative_amount():
    """现金分红行(份额 0、金额 -17.56):份额×价推算得 0,必须靠金额才能扣减净投入。"""
    cash_dividend = Record(shares=0, price=0, amount=-17.56)
    assert purchase_amount(cash_dividend) == -17.56


def test_reinvested_dividend_row_contributes_zero():
    """红利再投资行(份额 12.34、金额未落库):份额白涨、无现金进出 → 贡献 0。"""
    assert purchase_amount(Record(shares=12.34, price=0, amount=None)) == 0.0


# ===== 逐日现金流组装 =====


def test_net_invested_counts_dividend_and_actual_redemption():
    """净投入 = Σ买入金额 − Σ赎回实际到账;现金分红(负额)使净投入减少。

    赎回的扣减记**次日**(2026-10-14 修正:与份额消失日对齐,赎回日市值仍含
    该份额)——本例赎回 1-3,扣减落在 1-4,区间扩到 1-4 才能看到。
    """
    start, end = date(2026, 1, 1), date(2026, 1, 4)
    rows = flow_rows(
        [
            {'date': date(2026, 1, 1), 'type': 'buy', 'amount': purchase_amount(Record(shares=100, price=1.0, amount=99.9))},
            {'date': date(2026, 1, 2), 'type': 'buy', 'amount': purchase_amount(Record(shares=0, price=0, amount=-17.56))},
            {'date': date(2026, 1, 3), 'type': 'sell', 'amount': redemption_amount(Record(shares=50, price=1.0, amount=49.75))},
        ],
        start,
        end,
    )
    by_date = {row['flow_date']: row for row in rows}
    assert by_date[date(2026, 1, 1)]['cumulative_invested'] == 99.9
    assert by_date[date(2026, 1, 2)]['cumulative_invested'] == 99.9 - 17.56
    # 赎回日(1-3)不扣:市值口径赎回当日仍持有,盈亏不被赎回流出污染
    assert by_date[date(2026, 1, 3)]['cumulative_invested'] == 99.9 - 17.56
    assert by_date[date(2026, 1, 3)]['cash_flow'] == 0.0
    # 次日(1-4)才扣,与份额消失日同日
    assert by_date[date(2026, 1, 4)]['cumulative_invested'] == 99.9 - 17.56 - 49.75
    # cash_flow 是资金流向(与净投入符号相反):买入为负、赎回为正、分红为正(钱回来了)
    assert by_date[date(2026, 1, 2)]['cash_flow'] == 17.56
    assert by_date[date(2026, 1, 4)]['cash_flow'] == 49.75


def test_redemption_on_range_end_lands_outside():
    """赎回日 = 区间末日:扣减落在区间外,末日行 cum 不扣——
    与市值口径一致(份额末日仍持有,次日起消失),快照盈亏不被污染。"""
    rows = flow_rows(
        [{'date': date(2026, 1, 3), 'type': 'sell', 'amount': 49.75}],
        date(2026, 1, 1),
        date(2026, 1, 3),
    )
    assert all(row['cumulative_invested'] == 0.0 for row in rows)
    assert all(row['cash_flow'] == 0.0 for row in rows)


def test_redemption_before_range_counts_into_carry():
    """区间前的历史赎回(次日落在区间内或更早)照常进历史累计,净投入不断崖。"""
    rows = flow_rows(
        [
            {'date': date(2025, 12, 20), 'type': 'buy', 'amount': 500.0},
            {'date': date(2025, 12, 30), 'type': 'sell', 'amount': 50.0},
        ],
        date(2026, 1, 1),
        date(2026, 1, 2),
    )
    assert all(row['cumulative_invested'] == 450.0 for row in rows)


def test_history_before_range_is_carried_in():
    """区间开始前的历史交易必须先计入累计净投入,否则区间查询出现断崖。"""
    rows = flow_rows(
        [{'date': date(2025, 12, 20), 'type': 'buy', 'amount': 500.0}],
        date(2026, 1, 1),
        date(2026, 1, 2),
    )
    assert all(row['cumulative_invested'] == 500.0 for row in rows)
    # 区间内没有现金流的那天显式写 0.0(负零落库会显示成「-0」)
    assert all(row['cash_flow'] == 0.0 for row in rows)
