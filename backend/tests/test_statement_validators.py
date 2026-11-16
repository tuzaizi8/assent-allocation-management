"""交易记录分级校验单测(纯函数)。

分级口径:error 拦住落库, warning 只提示放行。这里的用例覆盖每条规则的
正反两面与分级边界(偏差小于噪声不报、超出容差才拦)。
"""

from datetime import date, timedelta

import pytest

from module_portfolio.service.statement_adapters import (
    BUY_WORDS as ADAPTER_BUY_WORDS,
    SELL_WORDS as ADAPTER_SELL_WORDS,
)
from module_portfolio.service.statement_validators import (
    BUY_WORDS,
    SELL_WORDS,
    direction_of,
    validate_records,
)

TODAY = date(2026, 5, 20)


def record(**overrides) -> dict:
    """一条合法的买入记录,按需覆盖字段。"""
    base = {
        'row': 2,
        'type': 'purchase',
        'fund_code': '000001',
        'fund_name': '华夏成长混合',
        'date': '2026-05-08',
        'amount': 100.0,
        'shares': 80.0,
        'unit_price': 1.25,
        'fee': 0.0,
        'order_no': 'A001',
    }
    base.update(overrides)
    return base


def errors_of(records: list[dict], **kwargs) -> list:
    _, errors, _ = validate_records(records, today=TODAY, **kwargs)
    return errors


class TestBlockingRules:
    """error 级:拦住落库。"""

    def test_valid_record_passes(self):
        kept, errors, warnings = validate_records([record()], today=TODAY)
        assert len(kept) == 1
        assert not errors and not warnings

    def test_fund_code_must_be_six_digits(self):
        assert errors_of([record(fund_code='12345')])[0].field == 'fundCode'
        assert errors_of([record(fund_code='')])[0].field == 'fundCode'
        assert errors_of([record(fund_code='00001X')])[0].field == 'fundCode'

    def test_date_must_be_parsable(self):
        assert errors_of([record(date=None)])[0].field == 'date'
        assert errors_of([record(date='2026年5月8日')])[0].field == 'date'

    def test_negative_shares_blocked(self):
        assert errors_of([record(shares=-1, amount=0, unit_price=0)])[0].field == 'shares'

    def test_redemption_without_shares_blocked(self):
        issues = errors_of([record(type='redemption', shares=0, unit_price=0)])
        assert any(issue.field == 'shares' for issue in issues)

    def test_unknown_direction_blocked(self):
        issues = errors_of([record(type='')])
        assert any(issue.field == 'type' for issue in issues)

    def test_amount_deviation_over_tolerance_blocked(self):
        # 份额×净值 = 80 * 1.25 = 100,金额写成 150 → 偏差 50 元,超容差
        issues = errors_of([record(amount=150.0)])
        assert any(issue.field == 'amount' and issue.level == 'error' for issue in issues)

    def test_duplicate_order_no_blocked(self):
        issues = errors_of([record(), record(row=3, order_no='A001')])
        assert any(issue.field == 'orderNo' for issue in issues)

    def test_same_order_no_across_funds_is_allowed(self):
        """支付宝订单号是**组合批次号**:同一订单跨多只基金本来就重复,不是错(2026-09-20 实测 12 条误判)。"""
        issues = errors_of([record(), record(row=3, fund_code='110011', order_no='A001')])
        assert not [issue for issue in issues if issue.field == 'orderNo']

    def test_same_order_no_across_directions_is_allowed(self):
        """同一组合批次里买、卖各一行也正常——键里带方向,方向不同即不同键。"""
        issues = errors_of([record(), record(row=3, type='redemption', order_no='A001')])
        assert not [issue for issue in issues if issue.field == 'orderNo']

    def test_error_row_is_not_kept(self):
        kept, _, _ = validate_records(
            [record(fund_code='bad', order_no='X1'), record(row=3, order_no='X2')], today=TODAY
        )
        assert len(kept) == 1
        assert kept[0]['order_no'] == 'X2'

    def test_tolerance_can_be_overridden_by_adapter(self):
        # 支付宝 PDF 转 Excel 会有分位漂移:适配器把相对容差放宽到 2% 后不再拦
        issues = errors_of([record(amount=101.5)], tolerance={'amount_vs_value': 0.02})
        assert not issues


class TestWarningRules:
    """warning 级:只提示,照样放行。"""

    def test_future_date_warns_but_passes(self):
        future = (TODAY + timedelta(days=1)).isoformat()
        kept, errors, warnings = validate_records([record(date=future)], today=TODAY)
        assert not errors and len(kept) == 1
        assert warnings[0].field == 'date'

    def test_zero_unit_price_backfilled_with_warning(self):
        kept, errors, warnings = validate_records([record(unit_price=0)], today=TODAY)
        assert not errors
        assert kept[0]['unit_price'] == 1.25
        assert warnings[0].field == 'unitPrice'

    def test_small_fee_deviation_warns(self):
        # 偏差 0.5 元:超过噪声 0.005 但远小于容差 → 只告警
        _, errors, warnings = validate_records([record(amount=100.5)], today=TODAY)
        assert not errors
        assert warnings[0].field == 'amount'

    def test_rounding_noise_silent(self):
        _, errors, warnings = validate_records([record(amount=100.002)], today=TODAY)
        assert not errors and not warnings

    def test_warning_row_keeps_its_own_row_ref(self):
        kept, _, warnings = validate_records([record(row=7, unit_price=0)], today=TODAY)
        assert warnings[0].row == 7
        assert kept[0]['row'] == 7

    def test_guessed_direction_warns_but_passes(self):
        """方向是靠申请份额推断出来的(适配器标 `_direction_from_shares`):放行 + 一条告警。

        「定投卖出」被判成买入那轮就是这类行——它当时连告警都没有,预览页上看不出来。
        """
        kept, errors, warnings = validate_records(
            [record(type='redemption', _direction_from_shares=True)], today=TODAY
        )
        assert len(kept) == 1 and not errors
        assert [issue.field for issue in warnings] == ['type']
        assert '推断为「赎回」' in warnings[0].message

    def test_explicit_direction_row_has_no_guess_warning(self):
        """类型列认得出方向的行不打扰(显式类型是绝大多数,不能满屏告警)。"""
        _, errors, warnings = validate_records([record()], today=TODAY)
        assert not errors and not warnings


class TestDirectionWordTable:
    """买卖方向的词表口径:两处实现必须一致,且**卖出词优先**。

    「定投卖出」同时含买入词(定投)与卖出词(卖)——买入词只是限定语,方向由动词决定。
    2026-09-22 之前两处都是先判买入词,蚂蚁对账单里的「定投卖出」因此被写成买入。
    """

    def test_two_word_lists_stay_in_sync(self):
        """适配器与校验层各有一份词表,只改一处就会让两处口径漂掉。"""
        assert BUY_WORDS == ADAPTER_BUY_WORDS
        assert SELL_WORDS == ADAPTER_SELL_WORDS

    @pytest.mark.parametrize(
        ('text', 'expected'),
        [
            ('用户买入', 'purchase'),
            ('定投买入', 'purchase'),
            ('申购', 'purchase'),
            ('用户卖出', 'redemption'),
            ('定投卖出', 'redemption'),
            ('转换转出', 'redemption'),
            ('转托管转出', 'redemption'),
            ('TA转换', ''),  # 词表认不出 → 交给「申请份额是否为空」兜底
        ],
    )
    def test_direction_table(self, text, expected):
        assert direction_of(text) == expected

    def test_normalized_value_passes_through(self):
        assert direction_of('purchase') == 'purchase'
        assert direction_of('redemption') == 'redemption'


class TestListItemRules:
    """列表式截图:净值未发布 → 待确认放行(只记金额);名称没解析出代码时把依据带进报错。"""

    def test_nav_pending_row_passes_with_warning(self):
        kept, errors, warnings = validate_records(
            [record(shares=0, unit_price=0, nav_pending=True)], today=TODAY
        )
        assert len(kept) == 1
        assert not errors
        assert any('份额待确认' in issue.message for issue in warnings)

    def test_pending_row_still_blocks_when_code_missing(self):
        errors = errors_of([record(fund_code='', shares=0, unit_price=0, nav_pending=True)])
        assert [issue.field for issue in errors] == ['fundCode']

    def test_resolve_note_attached_to_fund_code_error(self):
        errors = errors_of([record(fund_code='', resolve_note='匹配到多个候选，请人工确认：001323 / 002170')])
        assert len(errors) == 1
        assert '匹配到多个候选' in errors[0].message


class TestUnsupportedTypes:
    """账本表达不了的类型(红利再投资 / 分红):跳过并说清原因,而不是冒「买卖方向无法判定」。"""

    def test_unsupported_row_skipped_with_reason(self):
        kept, errors, warnings = validate_records(
            [record(row=14, type='', unsupported='红利再投资', fund_code='', shares=30.97, amount=0, unit_price=0)],
            today=TODAY,
        )
        assert kept == []
        assert not warnings
        assert len(errors) == 1
        assert errors[0].row == 14  # 行号要带上,预览的问题清单才能指到原图那一行
        assert errors[0].field == 'type'
        assert '红利再投资' in errors[0].message
        assert '暂不支持导入' in errors[0].message
        assert '已跳过' in errors[0].message
        assert '买卖方向无法判定' not in errors[0].message
