"""区间增量补数的「定向清理」单测(读路径懒补改增量后新增的纯函数)。

背景:全量重建靠 `DELETE` 保证「份额归零后尾部不再有该行」,而区间补数只 upsert、自己不删行,
所以要单独算一份待删集合。这里锁死两条边界:

- 份额归零 → 该行必须被清掉,否则快照列表尾部会留「已清仓却还在」的幽灵行;
- 份额>0 但**取不到净值**(被 `_build_snapshot_rows` 跳过、不在 keep_pairs 里)→ 绝不能删,
  否则会把「暂时缺净值」的行误删(2026-09-19 那次残缺数据的镜像陷阱)。

份额口径由 `shares_held_on_pairs` 提供:买入 `<=当日`计入、赎回 `<当日`才扣(赎回当日仍持有),
且结果不为负。纯函数直接测,无需 mock(样板对齐 test_snapshot_freshness.py)。
"""

from datetime import date

from module_portfolio.service.position_calc_util import shares_held_on_pairs
from module_portfolio.service.snapshot_service import plan_prune_pairs

DAY1 = date(2026, 9, 12)
DAY2 = date(2026, 9, 13)


def pairs(
    purchases: list[tuple[date, float]],
    redemptions: list[tuple[date, float]] | None = None,
) -> tuple[list[tuple[date, float]], list[tuple[date, float]]]:
    """构造 _collect_position_data 的产出形态:每只基金一份 (买入序列, 赎回序列)。"""
    return purchases, redemptions or []


class TestZeroShareRows:
    """份额归零:尾部不该再有该行,应纳入删除集。"""

    def test_full_redemption_next_day_is_pruned(self):
        """09-12 全额赎回 → 09-13 起份额为 0 → 删 09-13 那行。"""
        holdings = {'X': pairs([(date(2026, 9, 10), 100.0)], [(DAY1, 100.0)])}
        assert plan_prune_pairs(holdings, set(), DAY2, DAY2) == [(DAY2, 'X')]

    def test_redemption_day_row_is_kept(self):
        """赎回当日仍按持有计 → 该日不在删除集(否则会在赎回当天把行删掉)。"""
        holdings = {'X': pairs([(date(2026, 9, 10), 100.0)], [(DAY1, 100.0)])}
        assert plan_prune_pairs(holdings, set(), DAY1, DAY1) == []


class TestFloatResidue:
    """全额赎回后 `Σ买入 − Σ赎回` 的浮点残渣必须当作 0(否则快照尾部留幽灵行)。

    2026-09-20 实测:6 只已清仓基金(001718/006476/008764/011102/019005/539003)在最新快照里
    仍各出一行,份额 8.9e-16 ~ 1.4e-14(四舍五入到分都是 0.00),让快照列表的「基金数」显示 26,
    而在用持仓只有 20 —— 根因就是这里不归零:残渣 > 0 被当成「还持有」。
    """

    # 0.1 + 0.2 - 0.3 = 5.55e-17(浮点减法的经典残渣)
    RESIDUE = ([((DAY1), 0.1), ((DAY1), 0.2)], [(DAY1, 0.3)])
    RESIDUE_HOLDINGS = {'X': pairs(*RESIDUE)}

    def test_residue_share_is_treated_as_zero(self):
        """残渣不是 0 但小到无意义 → 归零。"""
        assert shares_held_on_pairs(self.RESIDUE[0], self.RESIDUE[1], DAY2) == 0.0

    def test_residue_tail_row_is_pruned(self):
        """归零后尾部行才进删除集 —— 否则连重建都清不掉这些幽灵行。"""
        assert plan_prune_pairs(self.RESIDUE_HOLDINGS, set(), DAY2, DAY2) == [(DAY2, 'X')]

    def test_redemption_day_row_still_kept(self):
        """赎回当日仍按持有计 → 当日不该被删(与「赎回次日起才扣除」口径一致)。

        注意这里**故意用容差比较**:0.1 + 0.2 = 0.30000000000000004(同一个浮点世界),
        要断言的是「残渣归零不影响真正持有的判定」,而不是浮点结果的最后一位。
        """
        assert abs(shares_held_on_pairs(self.RESIDUE[0], self.RESIDUE[1], DAY1) - 0.3) < 1e-9
        assert plan_prune_pairs(self.RESIDUE_HOLDINGS, set(), DAY1, DAY1) == []

    def test_real_small_holding_is_not_zeroed(self):
        """真实小额持仓(0.01 份)不能被误归零 —— 阈值只在 1e-6 份以下生效。"""
        assert shares_held_on_pairs([(DAY1, 0.01)], [], DAY2) == 0.01
        assert plan_prune_pairs({'X': pairs([(DAY1, 0.01)])}, {(DAY2, 'X')}, DAY2, DAY2) == []


class TestMissingNavRows:
    """取不到净值被跳过(不在 keep_pairs)时,绝不能因为「没算出来」就删。"""

    def test_held_fund_without_nav_is_not_pruned(self):
        """一直持有(份额>0)但本轮没算出任何行 → 删除集必须为空。"""
        holdings = {'Y': pairs([(date(2026, 9, 1), 100.0)])}
        assert plan_prune_pairs(holdings, set(), DAY1, DAY2) == []

    def test_mixed_range_only_zero_share_removed(self):
        """区间两天:A 第二天归零(删),B 一直持有(不删),A 第一天仍持有(不删)。"""
        holdings = {
            'A': pairs([(date(2026, 9, 1), 10.0)], [(DAY1, 10.0)]),
            'B': pairs([(date(2026, 9, 1), 20.0)]),
        }
        assert plan_prune_pairs(holdings, {(DAY1, 'A')}, DAY1, DAY2) == [(DAY2, 'A')]


class TestComputedRows:
    """本轮算出来的行不会进删除集。"""

    def test_computed_held_row_not_pruned(self):
        holdings = {'X': pairs([(date(2026, 9, 1), 5.0)])}
        assert plan_prune_pairs(holdings, {(DAY1, 'X'), (DAY2, 'X')}, DAY1, DAY2) == []


class TestEmptyInputs:
    """没有可算的基金时不做任何删除。"""

    def test_no_funds(self):
        assert plan_prune_pairs({}, set(), DAY1, DAY2) == []

    def test_empty_range_still_safe(self):
        """区间只有一天且该基金从未持有过 → 归零的那天在删除集,持有中的不入集。"""
        holdings = {'X': pairs([(date(2026, 9, 1), 1.0)], [(date(2026, 9, 2), 1.0)])}
        assert plan_prune_pairs(holdings, set(), DAY1, DAY1) == [(DAY1, 'X')]
