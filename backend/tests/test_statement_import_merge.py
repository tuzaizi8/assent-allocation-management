"""交易导入「按平台累加」判重的单测(纯函数,不需要 DB)。

判重键:买入 (日期, 基金代码, 方向, 金额)、赎回 (日期, 基金代码, 方向, 份额);容差内配对、
多重集计数(库里两条相同记录只能压掉新文件里的两条);判不了方向的记录一律视为新记录。
跨平台隔离由调用方按平台圈 `existing` 实现,故这里只按「传进来的 existing」判定。
"""

from module_portfolio.service.statement_import_merge import plan_import_merge


def buy(
    tx_date: str,
    code: str = '000001',
    amount: float = 1000.0,
    shares: float = 0.0,
    unit_price: float = 0.0,
) -> dict:
    return {
        'date': tx_date,
        'fund_code': code,
        'type': '买入',
        'amount': amount,
        'shares': shares,
        'unit_price': unit_price,
    }


def sell(tx_date: str, code: str = '000001', shares: float = 10.0) -> dict:
    return {'date': tx_date, 'fund_code': code, 'type': '赎回', 'amount': 0.0, 'shares': shares, 'unit_price': 0.0}


class TestIdempotentReimport:
    """同一份文件再导一次 → 全部判重丢弃,一条不落(「按平台累加」最基本的幂等性)。"""

    def test_full_overlap_keeps_nothing(self):
        existing = [buy('2021-06-01'), buy('2022-01-04', amount=2000.0), sell('2023-05-06')]
        kept, skipped = plan_import_merge(list(existing), existing)
        assert kept == []
        assert skipped == 3

    def test_rolling_window_only_appends_new_dates(self):
        """库里有支付宝 2022~2025,新文件是 2022~2026(平台只留 5 年)→ 只补 2026 的。"""
        existing = [buy('2022-03-01'), buy('2024-03-01'), buy('2025-03-01')]
        kept, skipped = plan_import_merge([*existing, buy('2026-03-01')], existing)
        assert [row['date'] for row in kept] == ['2026-03-01']
        assert skipped == 3

    def test_partial_overlap_appends_only_new(self):
        """场景 1:先导 2021~2022、再导 2022~2023 → 边界日重叠的丢弃,其余追加(库里并集)。"""
        existing = [buy('2021-06-01'), buy('2022-01-04')]
        kept, skipped = plan_import_merge([buy('2022-01-04'), buy('2022-08-09'), buy('2023-01-01')], existing)
        assert [row['date'] for row in kept] == ['2022-08-09', '2023-01-01']
        assert skipped == 1


def reinvest(tx_date: str, code: str, shares: float) -> dict:
    """红利再投资落成的买入行:金额 0、份额 N、单价 0(0 成本买入)。"""
    return {
        'date': tx_date,
        'fund_code': code,
        'type': '买入',
        'amount': 0.0,
        'shares': shares,
        'unit_price': 0.0,
    }


class TestDividendRows:
    """分红行的判重:红利再投资是「金额 0 + 份额 N」的买入行,同一天可能有两笔。"""

    def test_two_reinvestments_same_day_both_kept(self):
        """003547 的 2025-07-03 就是两笔(5.86 + 3.91):空库导入必须两条都留下。"""
        rows = [reinvest('2025-07-03', '003547', 5.86), reinvest('2025-07-03', '003547', 3.91)]
        kept, skipped = plan_import_merge(rows, [])
        assert (len(kept), skipped) == (2, 0)

    def test_reimport_of_reinvestments_skips_both(self):
        rows = [reinvest('2025-07-03', '003547', 5.86), reinvest('2025-07-03', '003547', 3.91)]
        kept, skipped = plan_import_merge(list(rows), rows)
        assert (len(kept), skipped) == (0, 2)

    def test_reinvestment_matched_by_shares_not_by_zero_amount(self):
        """库里只有 5.86 那笔时,新文件的两笔应该只压掉 5.86、留下 3.91(按份额比,不是都算 0)。"""
        existing = [reinvest('2025-07-03', '003547', 5.86)]
        rows = [reinvest('2025-07-03', '003547', 5.86), reinvest('2025-07-03', '003547', 3.91)]
        kept, skipped = plan_import_merge(rows, existing)
        assert [row['shares'] for row in kept] == [3.91]
        assert skipped == 1

    def test_cash_dividend_matched_by_its_negative_amount(self):
        """现金分红是「0 份额 + 负金额」:金额非 0,重导照样判得掉。"""
        cash = {'date': '2023-11-16', 'fund_code': '003547', 'type': '买入', 'amount': -17.56, 'shares': 0.0, 'unit_price': 0.0}
        kept, skipped = plan_import_merge([dict(cash)], [dict(cash)])
        assert (len(kept), skipped) == (0, 1)


class TestMultisetMatching:
    """同一个键可能对应多笔真实交易:配对是「多重集」而不是集合去重。"""

    def test_two_existing_one_incoming(self):
        existing = [buy('2026-05-08'), buy('2026-05-08')]
        kept, skipped = plan_import_merge([buy('2026-05-08')], existing)
        assert (len(kept), skipped) == (0, 1)

    def test_one_existing_two_incoming(self):
        kept, skipped = plan_import_merge([buy('2026-05-08'), buy('2026-05-08')], [buy('2026-05-08')])
        assert (len(kept), skipped) == (1, 1)

    def test_three_existing_two_incoming(self):
        kept, skipped = plan_import_merge([buy('2026-05-08')] * 2, [buy('2026-05-08')] * 3)
        assert (len(kept), skipped) == (0, 2)


class TestTolerance:
    """容差吸收不同导出件的分位/手续费口径差;明显不同的金额/份额必须保留。"""

    def test_amount_within_abs_tolerance(self):
        kept, skipped = plan_import_merge([buy('2026-05-08', amount=1000.01)], [buy('2026-05-08', amount=1000.00)])
        assert (kept, skipped) == ([], 1)

    def test_amount_beyond_tolerance(self):
        kept, skipped = plan_import_merge([buy('2026-05-08', amount=1001.00)], [buy('2026-05-08', amount=1000.00)])
        assert (len(kept), skipped) == (1, 0)

    def test_tolerance_does_not_scale_with_amount(self):
        """容差刻意不随金额放大:10 万的两笔只差 50 元也按两笔处理(误判＝丢数据,漏判才可见)。"""
        kept, skipped = plan_import_merge([buy('2026-05-08', amount=100050.0)], [buy('2026-05-08', amount=100000.0)])
        assert (len(kept), skipped) == (1, 0)

    def test_shares_tolerance_for_redemption(self):
        kept, skipped = plan_import_merge([sell('2026-05-08', shares=30.4)], [sell('2026-05-08', shares=30.0)])
        assert (kept, skipped) == ([], 1)
        kept, skipped = plan_import_merge([sell('2026-05-08', shares=31.0)], [sell('2026-05-08', shares=30.0)])
        assert (len(kept), skipped) == (1, 0)


class TestKeyFields:
    """买入比金额、赎回比份额;方向不同不互相误判;判不了的一律当新记录。"""

    def test_buy_and_sell_same_day_do_not_collide(self):
        kept, skipped = plan_import_merge([sell('2026-05-08', shares=10.0)], [buy('2026-05-08', amount=1000.0)])
        assert (len(kept), skipped) == (1, 0)

    def test_buy_amount_fallback_to_shares(self):
        """买入金额缺失时按**份额**兜底。

        2026-09-22 改:此前按「份额 × 单价」兜底。红利再投资是「金额 0 + 份额 N」的买入行、
        单价也是 0,两边都算成 0 → 同一天两笔再投(003547 的 5.86 + 3.91)互相混、重导分辨不出。
        """
        existing = [buy('2026-05-08', amount=0.0, shares=100.0)]
        kept, skipped = plan_import_merge([buy('2026-05-08', amount=0.0, shares=100.0)], existing)
        assert (kept, skipped) == ([], 1)

    def test_unjudgeable_rows_are_treated_as_new(self):
        """缺日期/基金/方向的判不了 → 不判重、当新记录(宁可重复也不丢)。"""
        existing = [buy('2026-05-08'), {'date': '', 'fund_code': '000001', 'type': '买入', 'amount': 1000.0}]
        incoming = [
            {'date': '', 'fund_code': '000001', 'type': '买入', 'amount': 1000.0},
            {'date': '2026-05-08', 'fund_code': '', 'type': '买入', 'amount': 1000.0},
            {'date': '2026-05-08', 'fund_code': '000001', 'type': '其它', 'amount': 1000.0},
        ]
        kept, skipped = plan_import_merge(incoming, existing)
        assert (len(kept), skipped) == (3, 0)


class TestPlatformIsolation:
    """跨平台不判重:调用方只把「本平台」的已有记录传进来,另一平台的记录必然全部保留。"""

    def test_other_platform_rows_are_all_kept(self):
        tiantian_new = [buy('2021-06-01', amount=1000.0), sell('2022-01-04', code='161725')]
        kept, skipped = plan_import_merge(tiantian_new, existing=[])
        assert kept == tiantian_new
        assert skipped == 0
