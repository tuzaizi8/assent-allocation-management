"""截图导入的下单切分单测:15:00 是基金收盘线,之后下单按下一交易日净值成交。

两类事实分开钉:① 适配器能不能从日期格里认出**下单时刻**;② 时刻 → 确认日的换算。
"""

from datetime import date

from module_portfolio.entity.vo.position_vo import (
    PurchaseRecordCreateModel,
    RedemptionRecordCreateModel,
)
from module_portfolio.service.position_calc_util import next_confirm_date
from module_portfolio.service.statement_adapters import ADAPTERS, _order_minutes, _parse_date
from module_portfolio.service.statement_import_service import StatementImportService

ALIPAY_LIST = ADAPTERS['alipay_trade_list']
TIANTIAN_LIST = ADAPTERS['tiantian_trade_query']


class TestOrderMinutes:
    def test_time_bearing_pattern_extracts_minutes(self):
        """带时分:14:53 → 893 分,15:01 → 901 分。"""
        assert _order_minutes('2026-09-01 14:53', ALIPAY_LIST) == 14 * 60 + 53
        assert _order_minutes('2026-09-01 15:01', ALIPAY_LIST) == 15 * 60 + 1

    def test_date_only_means_unknown_not_midnight(self):
        """只有日期 = 没识别到时间,返回 None;不能当 0 点(那会被当成 15 点前)。"""
        assert _order_minutes('2026-09-01', ALIPAY_LIST) is None

    def test_no_year_pattern_needs_year_from_group_header(self):
        """天天基金截图是 '09-01 15:01',年份取自月份分组标题。"""
        assert _order_minutes('09-01 15:01', TIANTIAN_LIST, year='2026') == 15 * 60 + 1
        assert _order_minutes('09-01 15:01', TIANTIAN_LIST) is None

    def test_date_parsing_unchanged_when_time_present(self):
        """加抽时刻不能影响既有日期解析结果。"""
        assert _parse_date('2026-09-01 15:01', ALIPAY_LIST) == '2026-09-01'
        assert _parse_date('09-01 15:01', TIANTIAN_LIST, year='2026') == '2026-09-01'


class TestOrderConfirmDate:
    def test_before_cutoff_keeps_same_day(self):
        """14:53 下单 → 当日确认(当日净值)。"""
        assert (
            StatementImportService.order_confirm_date('2026-09-01', 14 * 60 + 53) == '2026-09-01'
        )

    def test_at_cutoff_still_same_day(self):
        """15:00 整点仍是收盘那一刻的成交,按当日。"""
        assert StatementImportService.order_confirm_date('2026-09-01', 15 * 60) == '2026-09-01'

    def test_after_cutoff_shifts_one_day(self):
        """15:01 下单 → 顺延到下一日(非交易日再由 resolve_target_nav 顺延)。"""
        assert (
            StatementImportService.order_confirm_date('2026-09-01', 15 * 60 + 1) == '2026-09-02'
        )

    def test_month_boundary(self):
        """月底 15:00 后下单跨月。"""
        assert StatementImportService.order_confirm_date('2026-09-30', 16 * 60) == '2026-10-01'

    def test_year_boundary(self):
        """年末 15:00 后下单跨年。"""
        assert StatementImportService.order_confirm_date('2026-12-31', 20 * 60) == '2027-01-01'

    def test_weekend_order_rolls_into_next_week(self):
        """周五 15:00 后 → 周六(交由净值解析顺延到周一)。"""
        assert date.fromisoformat(
            StatementImportService.order_confirm_date('2026-09-04', 15 * 60 + 30)
        ).weekday() == 5


class TestManualEntryCutoff:
    def test_purchase_model_defaults_to_before_cutoff(self):
        """手工录入默认 15:00 前:不传该字段时确认日就是所选日期。"""
        model = PurchaseRecordCreateModel(
            fundCode='000218', amount=100.0, purchaseDate='2026-09-01'
        )
        assert model.after_cutoff is False

    def test_models_accept_after_cutoff_alias(self):
        """前端传驼峰 afterCutoff;买入与赎回两个 VO 都认。"""
        purchase = PurchaseRecordCreateModel(
            fundCode='000218', amount=100.0, purchaseDate='2026-09-01', afterCutoff=True
        )
        redemption = RedemptionRecordCreateModel(
            fundCode='000218', shares=10.0, redemptionDate='2026-09-01', afterCutoff=True
        )
        assert purchase.after_cutoff is True
        assert redemption.after_cutoff is True

    def test_next_confirm_date_shifts_one_day(self):
        """开关打开:确认日顺延一日(非交易日再由净值解析顺延)。"""
        assert next_confirm_date('2026-09-01') == '2026-09-02'
        assert next_confirm_date(date(2026, 9, 30)) == '2026-10-01'


class TestApplyOrderCutoff:
    @staticmethod
    def _record(order_date: str, minutes: int | None) -> dict:
        return {'date': order_date, '_order_minutes': minutes, 'page': 1, 'row': 1}

    def test_shift_only_when_time_known_and_after_cutoff(self):
        records = [
            self._record('2026-09-01', 14 * 60 + 53),
            self._record('2026-09-01', 15 * 60 + 1),
        ]
        warnings = StatementImportService._apply_order_cutoff(records)
        assert [r['date'] for r in records] == ['2026-09-01', '2026-09-02']
        assert records[1].get('_confirm_shifted') is True
        assert warnings == []

    def test_redemption_uses_the_same_cutoff(self):
        """赎回/卖出与买入同一条 15:00 线:切分不按方向过滤(防后人加方向分支时漏掉卖出)。

        赎回的确认日同样是「15:00 前按当日净值、之后按下一交易日净值」,晚一天会连带
        把到账金额与快照的份额扣减日一起推错。
        """
        records = [
            {'date': '2026-09-01', '_order_minutes': 14 * 60 + 53, 'type': '赎回', 'page': 1, 'row': 1},
            {'date': '2026-09-01', '_order_minutes': 15 * 60 + 1, 'type': '赎回', 'page': 1, 'row': 2},
            {'date': '2026-09-01', '_order_minutes': 15 * 60 + 1, 'type': '卖出', 'page': 1, 'row': 3},
        ]
        assert StatementImportService._apply_order_cutoff(records) == []
        assert [r['date'] for r in records] == ['2026-09-01', '2026-09-02', '2026-09-02']

    def test_unknown_time_keeps_date_and_warns(self):
        """识别不到时刻:不改日期,但必须告警——静默按当日会把 15:00 后的单子算早一天。"""
        records = [self._record('2026-09-01', None)]
        warnings = StatementImportService._apply_order_cutoff(records)
        assert records[0]['date'] == '2026-09-01'
        assert len(warnings) == 1
        assert warnings[0].level == 'warning'
        assert warnings[0].field == 'date'
        assert '15:00' in warnings[0].message
