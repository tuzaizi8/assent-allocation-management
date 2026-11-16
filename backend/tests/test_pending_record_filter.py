"""待确认交易过滤口径单测(status='0' 不参与份额与现金流)。

对齐真实数据的口径要求:待确认买入的份额未定、待确认赎回只有份额没有到账净值,
若参与计算,赎回会「份额已扣、钱没记回来」被算成亏损。纯函数直接测,无需 mock。
"""

from dataclasses import dataclass

from module_portfolio.service.position_calc_util import (
    filter_effective_records,
    is_effective_record,
)


@dataclass
class FakeRecord:
    """只需 status 与一个可辨识字段,够验证过滤即可。"""

    status: str | None
    tag: str = ''


class TestIsEffectiveRecord:
    def test_pending_is_not_effective(self):
        assert is_effective_record('0') is False

    def test_confirmed_is_effective(self):
        assert is_effective_record('1') is True

    def test_missing_status_counts_as_effective(self):
        """旧数据可能没有该字段:按已生效处理,避免历史记录被整批忽略。"""
        assert is_effective_record(None) is True


class TestFilterEffectiveRecords:
    def test_drops_pending_records(self):
        records = [
            FakeRecord(status='1', tag='已确认'),
            FakeRecord(status='0', tag='待确认'),
            FakeRecord(status='1', tag='已确认2'),
        ]
        assert [r.tag for r in filter_effective_records(records)] == ['已确认', '已确认2']

    def test_keeps_missing_status(self):
        records = [FakeRecord(status=None, tag='旧数据')]
        assert [r.tag for r in filter_effective_records(records)] == ['旧数据']

    def test_empty_input(self):
        assert filter_effective_records([]) == []
