"""快照滞后判定单测(读路径懒补快照的纯函数关卡)。

对齐真实数据踩到的坑:快照只在「交易后回填」与「手动生成/重建」两处写入,而净值当晚才发布:
- 日期滞后:09-15 凌晨重建时当日净值未发布,09-15 行沿用 09-14 的净值 → 当日收益恒为 0
  (2026-09-15 实测:持仓市值随实时净值下跌,收益率曲线却一动不动);
- 同日不一致:某基金数据源发布滞后,09-12~09-15 四天都写着 09-11 的 8.1177,而真实 09-14
  已是 8.0448——只看日期会把这种情况当「新鲜」。

纯函数直接测,无需 mock(样板对齐 test_twr_cashflow_strip.py / test_pending_record_filter.py)。
"""

from datetime import date

from module_portfolio.service.position_calc_util import is_snapshot_nav_stale

NAV_0911 = 8.1177
NAV_0914 = 8.0448


def nav_series(*pairs: tuple[str, float]) -> list[dict]:
    """构造升序净值序列(同 get_fund_nav 返回形态:nav_date + unit_nav)。"""
    return [{'nav_date': day, 'unit_nav': value} for day, value in pairs]


class TestEmptyInputs:
    """判不了就不补:拿不到快照日/净值序列时一律不触发重建。"""

    def test_no_snapshot_date(self):
        assert is_snapshot_nav_stale(None, {'000001': 1.235}, {'000001': nav_series(('2026-09-14', 1.235))}) is False

    def test_no_snapshot_rows(self):
        assert is_snapshot_nav_stale('2026-09-15', {}, {'000001': nav_series(('2026-09-15', 1.25))}) is False

    def test_no_nav_cache(self):
        assert is_snapshot_nav_stale('2026-09-15', {'000001': 1.235}, {}) is False
        assert is_snapshot_nav_stale('2026-09-15', {'000001': 1.235}, None) is False


class TestDateLag:
    """规则①:最新净值日已晚于快照日 → 快照少了一段真实行情。"""

    def test_nav_newer_than_snapshot_is_stale(self):
        navs = nav_series(('2026-09-14', 1.235), ('2026-09-15', 1.25))
        assert is_snapshot_nav_stale('2026-09-14', {'000001': 1.235}, {'000001': navs}) is True

    def test_snapshot_date_accepts_date_object(self):
        """调用方传的是 date(DAO 返回),内部统一成 yyyy-MM-dd 再比。"""
        navs = nav_series(('2026-09-14', 1.235), ('2026-09-15', 1.25))
        assert is_snapshot_nav_stale(date(2026, 9, 14), {'000001': 1.235}, {'000001': navs}) is True

    def test_same_day_is_not_date_lag(self):
        navs = nav_series(('2026-09-14', 1.235), ('2026-09-15', 1.25))
        assert is_snapshot_nav_stale('2026-09-15', {'000001': 1.25}, {'000001': navs}) is False


class TestSameDayMismatch:
    """规则②:日期没落后,但该日存的是「后到净值之前」取的旧根(270042 型)。"""

    def test_stale_root_on_same_day_is_stale(self):
        navs = nav_series(('2026-09-10', 8.0487), ('2026-09-11', NAV_0911), ('2026-09-14', NAV_0914))
        assert is_snapshot_nav_stale('2026-09-14', {'270042': NAV_0911}, {'270042': navs}) is True

    def test_correct_root_is_not_stale(self):
        navs = nav_series(('2026-09-10', 8.0487), ('2026-09-11', NAV_0911), ('2026-09-14', NAV_0914))
        assert is_snapshot_nav_stale('2026-09-14', {'270042': NAV_0914}, {'270042': navs}) is False

    def test_float_tolerance_absorbs_storage_precision(self):
        """落库精度误差(1e-7 量级)不该被当成滞后,否则会反复重建。"""
        navs = nav_series(('2026-09-15', 1.25))
        assert is_snapshot_nav_stale('2026-09-15', {'000001': 1.25 + 1e-7}, {'000001': navs}) is False

    def test_real_mismatch_beyond_tolerance(self):
        navs = nav_series(('2026-09-15', 1.25))
        assert is_snapshot_nav_stale('2026-09-15', {'000001': 1.2501}, {'000001': navs}) is True


class TestNonTradingDay:
    """非交易日快照取的是上一交易日那根净值:与快照构建同口径,不该判滞后。"""

    def test_weekend_uses_previous_root(self):
        navs = nav_series(('2026-09-10', 1.262), ('2026-09-11', 1.254))
        assert is_snapshot_nav_stale('2026-09-13', {'000001': 1.254}, {'000001': navs}) is False


class TestSkipUnjudgeableFunds:
    """判不了的单只基金跳过,不牵连其他基金、也不凭它触发重建。"""

    def test_fund_without_nav_records_is_skipped(self):
        navs = nav_series(('2026-09-15', 1.25))
        assert is_snapshot_nav_stale('2026-09-15', {'000001': 1.25, '001294': 0.9662}, {'000001': navs}) is False

    def test_empty_records_are_skipped(self):
        assert is_snapshot_nav_stale('2026-09-15', {'000001': 1.24}, {'000001': []}) is False

    def test_nav_not_yet_started_is_skipped(self):
        """目标日早于该基金首根净值(nav_at_or_before 取不到)→ 跳过。"""
        navs = nav_series(('2026-09-20', 1.0))
        assert is_snapshot_nav_stale('2026-09-15', {'000001': 1.24}, {'000001': navs}) is False

    def test_record_without_nav_date_is_skipped(self):
        assert is_snapshot_nav_stale('2026-09-15', {'000001': 1.24}, {'000001': [{'unit_nav': 1.24}]}) is False


class TestFutureDatedRecords:
    """净值序列里出现「未来日期」的脏记录:重建上界是今天,不能被它拖成永久滞后。"""

    def test_future_record_does_not_force_rebuild(self):
        navs = nav_series(('2026-09-14', 1.235), ('2026-09-30', 1.5))
        assert is_snapshot_nav_stale('2026-09-14', {'000001': 1.235}, {'000001': navs}, today='2026-09-16') is False

    def test_future_record_counts_once_it_is_reachable(self):
        """同一份数据,等 today 走到那根记录之后,它就是正常的最新净值日。"""
        navs = nav_series(('2026-09-14', 1.235), ('2026-09-30', 1.5))
        assert is_snapshot_nav_stale('2026-09-14', {'000001': 1.235}, {'000001': navs}, today='2026-09-30') is True

    def test_only_future_records_are_skipped(self):
        navs = nav_series(('2026-09-30', 1.5))
        assert is_snapshot_nav_stale('2026-09-14', {'000001': 1.235}, {'000001': navs}, today='2026-09-16') is False


class TestMultiFund:
    """多只基金:只要有一只不一致即滞后;全部一致才不重建。"""

    def test_one_of_many_mismatched_is_stale(self):
        nav_cache = {
            '000001': nav_series(('2026-09-15', 1.25)),
            '004814': nav_series(('2026-09-15', 2.0759)),
            '006228': nav_series(('2026-09-15', 1.6444)),
        }
        snapshot_navs = {'000001': 1.25, '004814': 2.0759, '006228': 1.65}
        assert is_snapshot_nav_stale('2026-09-15', snapshot_navs, nav_cache) is True

    def test_all_matched_is_not_stale(self):
        nav_cache = {
            '000001': nav_series(('2026-09-15', 1.25)),
            '004814': nav_series(('2026-09-15', 2.0759)),
        }
        snapshot_navs = {'000001': 1.25, '004814': 2.0759}
        assert is_snapshot_nav_stale('2026-09-15', snapshot_navs, nav_cache) is False
