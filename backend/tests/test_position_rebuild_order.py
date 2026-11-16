"""「重建持仓」重放顺序的纯函数单测。

顺序错了会连锁坏事:同日赎回先于买入重放会触发全额赎回软删,
随后的买入另建新持仓行,一笔持仓被拆成两代。
"""

from module_portfolio.service.statement_import_service import StatementImportService


def tx(type_: str, date_: str, record_id: int) -> dict:
    return {'type': type_, 'date': date_, 'record_id': record_id}


class TestReplayOrder:
    def test_date_ascending(self):
        """跨日期:早的先重放。"""
        queue = [tx('买入', '2026-06-01', 2), tx('买入', '2026-01-05', 1)]
        ordered = sorted(queue, key=StatementImportService._replay_order)
        assert [r['record_id'] for r in ordered] == [1, 2]

    def test_same_day_purchase_before_redemption(self):
        """同日:买入先于赎回,否则赎回先重放会误判全额赎回。"""
        queue = [
            tx('赎回', '2026-01-05', 3),
            tx('买入', '2026-01-05', 1),
            tx('买入', '2026-01-05', 2),
        ]
        ordered = sorted(queue, key=StatementImportService._replay_order)
        assert [r['type'] for r in ordered] == ['买入', '买入', '赎回']

    def test_stable_by_record_id_within_same_day_and_type(self):
        """同日同类型:按记录 id 稳定排序,重放结果可复现。"""
        queue = [tx('买入', '2026-01-05', 9), tx('买入', '2026-01-05', 4)]
        ordered = sorted(queue, key=StatementImportService._replay_order)
        assert [r['record_id'] for r in ordered] == [4, 9]

    def test_missing_date_sorts_first_and_survives(self):
        """日期缺失(理论不可达,防御):排最前且不抛异常。"""
        queue = [tx('买入', '2026-01-05', 1), tx('买入', None, 0)]
        ordered = sorted(queue, key=StatementImportService._replay_order)
        assert ordered[0]['record_id'] == 0
