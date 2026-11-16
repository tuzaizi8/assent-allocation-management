"""快照/现金流「写入互斥」单测:同用户并发写入时只有一个能真正落库。

背景(2026-09-18 实测):三个全量重建在 3 秒内并发提交(2 次手点 POST /snapshot/rebuild + 1 次
读路径懒补),各自「先清空再批量插」——并发的 DELETE 看不见别人未提交的行,于是快照被写成 3 份、
现金流被写成 2 份;快照列表那个「同日取一行现金流」的标量子查询遇到多行直接抛
CardinalityViolationError,列表接口 500,基金数与市值还被放大 3 倍。

互斥实现见 SnapshotService._try_lock_user_writes(PG 事务级 advisory lock 的 try 版)。
本文件只测「抢不到锁时的行为与参数口径」,全程 monkeypatch,不连真库、不连 Redis。
"""

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from exceptions.exceptions import ServiceWarning
from module_portfolio.service import snapshot_service
from module_portfolio.service.snapshot_service import SnapshotService

SNAPSHOT_DAY = date(2026, 9, 18)


def fake_session() -> Mock:
    """会话桩:commit/rollback 可断言;任何真实 SQL 都视为「不该发生」并直接失败。"""
    session = Mock()
    session.execute = AsyncMock(side_effect=AssertionError('抢不到写入锁时不应再向数据库发任何语句'))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def lock_session(acquired: bool) -> Mock:
    """只用于测锁获取本身:让 execute 交出 pg_try_advisory_xact_lock 的布尔结果。"""
    session = Mock()
    session.execute = AsyncMock(return_value=Mock(scalar=Mock(return_value=acquired)))
    return session


class FakeSnapshotRow:
    """is_snapshot_nav_stale 的入参只取 fund_code / nav 两个属性。"""

    def __init__(self, fund_code: str, nav: float):
        self.fund_code = fund_code
        self.nav = nav


def async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def async_raise(exc):
    async def _inner(*args, **kwargs):
        raise exc

    return _inner


async def lock_taken(_db, _user_id):
    return False


async def lock_free(_db, _user_id):
    return True


class TestLockAcquisition:
    """锁形态:必须是 try 版(不阻塞),并按 (命名空间, 用户) 成对传参。"""

    def test_uses_try_variant_with_namespace_and_user(self):
        session = lock_session(acquired=True)
        assert asyncio.run(SnapshotService._try_lock_user_writes(session, 42)) is True
        statement, params = session.execute.await_args.args
        assert str(statement).strip().lower().startswith('select pg_try_advisory_xact_lock(')
        assert params == {'ns': snapshot_service.SNAPSHOT_WRITE_LOCK_NS, 'user_id': 42}

    def test_returns_false_when_held_by_others(self):
        assert asyncio.run(SnapshotService._try_lock_user_writes(lock_session(acquired=False), 42)) is False


class TestClearRejectedWhenBusy:
    """清空与重建共用同一把锁:抢不到就回绝,绝不能先删后插。"""

    def test_clear_raises_and_touches_nothing(self, monkeypatch):
        monkeypatch.setattr(SnapshotService, '_try_lock_user_writes', lock_taken)
        session = fake_session()
        with pytest.raises(ServiceWarning):
            asyncio.run(SnapshotService.clear_snapshots_and_cash_flows(session, 1))
        session.execute.assert_not_awaited()
        session.commit.assert_not_awaited()

    def test_clear_proceeds_when_lock_acquired(self, monkeypatch):
        monkeypatch.setattr(SnapshotService, '_try_lock_user_writes', lock_free)
        monkeypatch.setattr(snapshot_service.DailySnapshotDao, 'delete_all_snapshots_for_user', async_return(3))
        monkeypatch.setattr(snapshot_service.DailyCashFlowDao, 'delete_all_cash_flows_for_user', async_return(2))
        result = asyncio.run(SnapshotService.clear_snapshots_and_cash_flows(fake_session(), 1))
        assert result == {'snapshots_deleted': 3, 'cash_flows_deleted': 2}


class TestRebuildRejectedWhenBusy:
    """全量重建:冷却键抢到、DB 写锁抢不到时必须抛业务提示,且不写库(其余重建入口靠它兜底)。"""

    def test_rebuild_raises_and_releases_own_cooldown(self, monkeypatch):
        released = []

        async def record_release(redis, user_id):
            released.append(user_id)

        monkeypatch.setattr(SnapshotService, '_acquire_rebuild_lock', lock_free)
        monkeypatch.setattr(SnapshotService, '_release_rebuild_lock', record_release)
        monkeypatch.setattr(SnapshotService, '_try_lock_user_writes', lock_taken)
        monkeypatch.setattr(snapshot_service.PositionDao, 'get_all_positions', async_return([]))
        monkeypatch.setattr(SnapshotService, '_get_funds_by_positions', async_return({}))
        monkeypatch.setattr(SnapshotService, '_collect_position_data', async_return(({}, [])))
        session = fake_session()
        with pytest.raises(ServiceWarning):
            asyncio.run(SnapshotService.rebuild_from_transactions_services(session, None, 7))
        # 本次没重建,冷却键要还回去,否则用户白等一个冷却窗口
        assert released == [7]
        session.commit.assert_not_awaited()

    def test_skip_cooldown_gate_for_read_path(self, monkeypatch):
        """读路径已持有冷却键(cooldown_held=True)时不再抢第二遍,直接走 DB 写锁。"""
        monkeypatch.setattr(
            SnapshotService, '_acquire_rebuild_lock', async_raise(AssertionError('不应重复抢冷却键'))
        )
        monkeypatch.setattr(SnapshotService, '_try_lock_user_writes', lock_taken)
        monkeypatch.setattr(snapshot_service.PositionDao, 'get_all_positions', async_return([]))
        monkeypatch.setattr(SnapshotService, '_get_funds_by_positions', async_return({}))
        monkeypatch.setattr(SnapshotService, '_collect_position_data', async_return(({}, [])))
        with pytest.raises(ServiceWarning):
            asyncio.run(
                SnapshotService.rebuild_from_transactions_services(fake_session(), None, 7, cooldown_held=True)
            )


class TestCooldownProbeWriteLock:
    """冷却键被占时先探写锁:空闲即放行(只是上次留下的冷却窗口),被占才回绝且文案可读。"""

    class FakeRedis:
        async def get(self, _key):
            return '1763000000'  # 冷却键的值 = 上次加锁时刻,放行时写进日志

    @staticmethod
    async def cooldown_busy(_redis, _user_id):
        return False

    def test_no_running_rebuild_proceeds(self, monkeypatch):
        """冷却键被占 + 写锁空闲 → 放行(否则用户点「重建快照」要白等十分钟)。"""
        release = AsyncMock()
        monkeypatch.setattr(SnapshotService, '_acquire_rebuild_lock', self.cooldown_busy)
        monkeypatch.setattr(SnapshotService, '_try_lock_user_writes', lock_free)
        monkeypatch.setattr(
            SnapshotService, '_rebuild_from_transactions', async_return({'rebuilt': {}})
        )
        monkeypatch.setattr(SnapshotService, '_release_rebuild_lock', release)

        result = asyncio.run(
            SnapshotService.rebuild_from_transactions_services(fake_session(), self.FakeRedis(), 7)
        )

        assert result == {'rebuilt': {}}
        # 放行不等于接管:不能去删别人还压着的冷却键
        release.assert_not_called()

    def test_running_rebuild_is_rejected_with_readable_message(self, monkeypatch):
        """冷却键被占 + 写锁被占 → 确有重建在执行,回绝且文案说清「正在执行中」。"""
        monkeypatch.setattr(SnapshotService, '_acquire_rebuild_lock', self.cooldown_busy)
        monkeypatch.setattr(SnapshotService, '_try_lock_user_writes', lock_taken)
        with pytest.raises(ServiceWarning) as excinfo:
            asyncio.run(
                SnapshotService.rebuild_from_transactions_services(fake_session(), None, 7)
            )
        assert '正在执行中' in str(excinfo.value)


class TestReadPathSkip:
    """读路径懒补:并发写入进行中时静默跳过——回滚、返回 False,且不误删冷却键。"""

    def test_returns_false_and_keeps_cooldown(self, monkeypatch):
        released = []
        monkeypatch.setattr(
            snapshot_service.DailySnapshotDao, 'get_latest_snapshot_date', async_return(SNAPSHOT_DAY)
        )
        monkeypatch.setattr(
            snapshot_service.DailySnapshotDao,
            'get_snapshots_in_range',
            async_return([FakeSnapshotRow('000001', 1.235)]),
        )
        monkeypatch.setattr(SnapshotService, '_prefetch_nav_records', async_return({}))
        monkeypatch.setattr(snapshot_service, 'is_snapshot_nav_stale', lambda *args: True)
        monkeypatch.setattr(SnapshotService, '_acquire_rebuild_lock', lock_free)
        # 读路径已改走区间增量补数(_refresh_range_services):这里让它抛 ServiceWarning,
        # 验证吞异常/保冷却键的行为与旧全量路径一致
        monkeypatch.setattr(
            SnapshotService,
            '_refresh_range_services',
            async_raise(ServiceWarning(message='已有重建正在进行，请稍后再试')),
        )
        monkeypatch.setattr(
            SnapshotService,
            'rebuild_from_transactions_services',
            async_raise(AssertionError('读路径不应再触发全量重建')),
        )
        monkeypatch.setattr(
            SnapshotService, '_release_rebuild_lock', lambda redis, user_id: released.append(user_id)
        )
        session = fake_session()
        assert asyncio.run(SnapshotService.ensure_fresh_services(session, None, 7)) is False
        assert released == []
        session.rollback.assert_awaited_once()

    def test_lazy_path_uses_incremental_tail_range(self, monkeypatch):
        """懒补契约:不再整段重算——只调一次 _refresh_range_services,区间「最新快照日~今天」并复用已取回的净值。"""
        captured: dict = {}

        async def record_refresh(_db, _redis, user_id, start_date, end_date, **kwargs):
            captured.update({'user_id': user_id, 'start': start_date, 'end': end_date, **kwargs})
            return {'snapshots_upserted': 1, 'cash_flows_upserted': 1, 'pruned': 0}

        nav_cache = {'000001': [{'nav_date': '2026-09-18', 'unit_nav': 1.235}]}
        monkeypatch.setattr(
            snapshot_service.DailySnapshotDao, 'get_latest_snapshot_date', async_return(SNAPSHOT_DAY)
        )
        monkeypatch.setattr(
            snapshot_service.DailySnapshotDao,
            'get_snapshots_in_range',
            async_return([FakeSnapshotRow('000001', 1.235)]),
        )
        monkeypatch.setattr(SnapshotService, '_prefetch_nav_records', async_return(nav_cache))
        monkeypatch.setattr(snapshot_service, 'is_snapshot_nav_stale', lambda *args: True)
        monkeypatch.setattr(SnapshotService, '_acquire_rebuild_lock', lock_free)
        monkeypatch.setattr(SnapshotService, '_refresh_range_services', record_refresh)
        monkeypatch.setattr(
            SnapshotService,
            'rebuild_from_transactions_services',
            async_raise(AssertionError('读路径不应再触发全量重建')),
        )
        monkeypatch.setattr(
            SnapshotService,
            '_generate_range',
            async_raise(AssertionError('读路径不该走 active-持仓口径(会与全量口径断层)')),
        )
        assert asyncio.run(SnapshotService.ensure_fresh_services(fake_session(), None, 7)) is True
        # 起点 = min(最新快照日, 今天往前回看 7 天),见 LAZY_REFRESH_LOOKBACK_DAYS
        expected_start = min(
            SNAPSHOT_DAY, date.today() - timedelta(days=snapshot_service.LAZY_REFRESH_LOOKBACK_DAYS - 1)
        )
        assert captured == {
            'user_id': 7,
            'start': expected_start,
            'end': date.today(),
            'nav_cache': nav_cache,
        }
