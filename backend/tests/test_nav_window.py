"""双窗口新鲜度判定的纯函数级测试。

窗口划分与 TTL 见 utils/nav_window_util(00:00/22:00 双失效点);
判定语义与 fund_nav_dao.is_nav_stale / get_nav_page 三态谓词同口径。
所有用例显式注入 now,保证 22 点前后跑测试结果一致。
"""

from datetime import datetime

from module_fund.dao.index_nav_dao import IndexNavDao
from utils.nav_window_util import window_start, window_ttl


def _dt(s: str) -> datetime:
    return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')


class TestWindowStart:
    def test_morning_window_starts_at_midnight(self):
        assert window_start(_dt('2026-09-07 09:00:00')) == _dt('2026-09-07 00:00:00')

    def test_just_before_deadline_still_uses_midnight(self):
        assert window_start(_dt('2026-09-07 21:59:59')) == _dt('2026-09-07 00:00:00')

    def test_deadline_exactly_switches_window(self):
        assert window_start(_dt('2026-09-07 22:00:00')) == _dt('2026-09-07 22:00:00')

    def test_late_night_window_starts_at_deadline(self):
        assert window_start(_dt('2026-09-07 23:59:00')) == _dt('2026-09-07 22:00:00')


class TestWindowTtl:
    def test_morning_write_lives_until_evening_deadline(self):
        assert window_ttl(_dt('2026-09-07 09:00:00')) == 13 * 3600

    def test_write_just_before_deadline_floors_at_minimum(self):
        # 21:59:30 写入距失效点仅 30s,取下限 60s——旧数据最多续命 1 分钟
        assert window_ttl(_dt('2026-09-07 21:59:30')) == 60

    def test_evening_write_lives_until_midnight(self):
        assert window_ttl(_dt('2026-09-07 22:00:00')) == 2 * 3600

    def test_write_just_before_midnight_floors_at_minimum(self):
        assert window_ttl(_dt('2026-09-07 23:59:30')) == 60


class TestStaleRecords:
    def make_records(self, latest: str) -> list[dict]:
        return [{'nav_date': latest, 'unit_nav': 1.0}]

    def test_empty_records_is_stale(self):
        assert IndexNavDao.is_stale_records([], _dt('2026-09-07 09:00:00')) is True

    def test_records_with_today_date_is_fresh(self):
        now = _dt('2026-09-07 09:00:00')
        assert (
            IndexNavDao.is_stale_records(self.make_records('2026-09-07'), None, now)
            is False
        )

    def test_yesterday_data_tried_this_morning_is_fresh_in_morning_window(self):
        # 昨晚发布昨天净值,今早已回源拉到 → 早窗口内不再回源
        now = _dt('2026-09-07 10:00:00')
        assert (
            IndexNavDao.is_stale_records(
                self.make_records('2026-09-06'), _dt('2026-09-07 09:00:00'), now
            )
            is False
        )

    def test_yesterday_data_last_tried_yesterday_is_stale_next_morning(self):
        # 跨天即过期:昨天试过、今天没试 → 今天首次访问即回源(修复 24h 锚点延迟)
        now = _dt('2026-09-07 09:00:00')
        assert (
            IndexNavDao.is_stale_records(
                self.make_records('2026-09-06'), _dt('2026-09-06 22:30:00'), now
            )
            is True
        )

    def test_morning_trial_does_not_block_evening_window(self):
        # 凌晨空转过(00:30),当晚 23:00 访问:晚窗口起点 22:00,00:30 早于它 → 过期可回源,
        # 拿到当晚发布的数据(纯跨天方案会在此被"今天已试过"挡住一天)
        now = _dt('2026-09-07 23:00:00')
        assert (
            IndexNavDao.is_stale_records(
                self.make_records('2026-09-06'), _dt('2026-09-07 00:30:00'), now
            )
            is True
        )

    def test_evening_trial_in_evening_window_is_fresh(self):
        now = _dt('2026-09-07 23:00:00')
        assert (
            IndexNavDao.is_stale_records(
                self.make_records('2026-09-06'), _dt('2026-09-07 22:30:00'), now
            )
            is False
        )

    def test_unparseable_latest_date_is_stale(self):
        now = _dt('2026-09-07 09:00:00')
        assert (
            IndexNavDao.is_stale_records(self.make_records('bad-date'), None, now)
            is True
        )
