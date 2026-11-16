"""持仓列表「服务端排序」单测:排序键是派生指标,必须先算完指标再排序、最后切片。

三个键(current_value / profit / profit_rate)由「份额×净值」与结转成本算出来,**SQL 里没有
对应列** → 服务层取全量头表行(is_page=False)、在内存排序、自己切片。这里把 DAO 与明细组装
换成替身,单独钉排序结果、分页契约(total/hasNext)、同值稳定性与「未知键回落默认」。
"""

import asyncio

import pytest

from module_portfolio.service.position_service import (
    POSITION_SORT_KEYS,
    PositionService,
)

# (positionId, currentValue, profit, profitRate) —— 故意让三个键的排序各不相同
ROWS = [
    {'positionId': 1, 'currentValue': 100.0, 'profit': -10.0, 'profitRate': -9.1},
    {'positionId': 2, 'currentValue': 900.0, 'profit': 5.0, 'profitRate': 0.6},
    {'positionId': 3, 'currentValue': 500.0, 'profit': 50.0, 'profitRate': 11.1},
    {'positionId': 4, 'currentValue': 500.0, 'profit': -30.0, 'profitRate': -5.6},
]


class FakePositionDao:
    """只回头表主键:编号与真实 DAO 一致(is_page=False 时 PageUtil 返回行列表)。"""

    calls: list[dict] = []

    @classmethod
    async def get_positions_page(cls, *args, **kwargs):
        cls.calls.append(kwargs)
        return [{'positionId': row['positionId']} for row in ROWS]


@pytest.fixture(autouse=True)
def patched(monkeypatch):
    async def noop_confirm(*args, **kwargs):
        return None

    async def fake_detail(query_db, redis, position_id, user_id, confirm_pending=False):
        return next(row for row in ROWS if row['positionId'] == position_id)

    FakePositionDao.calls = []
    monkeypatch.setattr('module_portfolio.service.position_service.PositionDao', FakePositionDao)
    monkeypatch.setattr(PositionService, '_confirm_pending_transactions', noop_confirm)
    monkeypatch.setattr(PositionService, 'get_position_detail_services', fake_detail)


def fetch(**kwargs) -> tuple[list[int], int, bool]:
    """跑一次列表查询,返回(本页 positionId 序, total, hasNext)。"""
    page = asyncio.run(PositionService.get_positions_services(None, None, 1, is_page=True, **kwargs))
    return [row['positionId'] for row in page.rows], page.total, page.has_next


def test_default_sort_is_current_value_desc():
    """不传排序 → 服务端默认「当前市值降序」(列表页默认视图)。"""
    assert fetch(page_num=1, page_size=3) == ([2, 3, 4], 4, True)


def test_unknown_key_falls_back_to_default():
    assert fetch(page_num=1, page_size=3, sort_by='不知道的键') == ([2, 3, 4], 4, True)


@pytest.mark.parametrize(
    ('sort_by', 'sort_order', 'expected'),
    [
        ('profit', 'desc', [3, 2, 1]),      # 50 / 5 / -10
        ('profit', 'asc', [4, 1, 2]),       # -30 / -10 / 5
        ('profit_rate', 'desc', [3, 2, 4]),  # 11.1 / 0.6 / -5.6
        ('profit_rate', 'asc', [1, 4, 2]),   # -9.1 / -5.6 / 0.6
        ('current_value', 'asc', [1, 3, 4]),  # 100 / 500 / 500(同值保持 position_id 序)
    ],
)
def test_each_metric_and_direction(sort_by, sort_order, expected):
    assert fetch(page_num=1, page_size=3, sort_by=sort_by, sort_order=sort_order)[0] == expected


def test_pages_are_continuous_and_ties_keep_row_order():
    """分页在排序之后:第 2 页接着第 1 页;两笔同市值(3、4)按 position_id 稳定,翻页不抖。"""
    assert fetch(page_num=1, page_size=2)[0] == [2, 3]
    assert fetch(page_num=2, page_size=2)[0] == [4, 1]
    assert fetch(page_num=3, page_size=2)[0] == []
    assert fetch(page_num=2, page_size=2)[1:] == (4, False)


def test_head_rows_are_fetched_without_pagination():
    """契约:排序键要算完指标才知道,DAO 必须按 is_page=False 取全量(先切页会切出错序)。"""
    fetch(page_num=2, page_size=3, sort_by='profit')
    assert FakePositionDao.calls[-1]['is_page'] is False


def test_sort_keys_expose_only_the_three_metrics():
    assert POSITION_SORT_KEYS == {
        'current_value': 'currentValue',
        'profit': 'profit',
        'profit_rate': 'profitRate',
    }
