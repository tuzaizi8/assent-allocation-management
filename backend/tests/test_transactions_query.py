"""交易明细查询的最小回归:按账号直查 + SQL 分页。

不连库:编译 SQLAlchemy 语句断言过滤条件与排序/分页键 —— 少一个 user_id 会跨账号串数据;
少一个稳定排序键,`LIMIT/OFFSET` 翻页就会漏行或重行(同一天多笔时旧实现靠遍历顺序碰巧对)。
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, union_all
from sqlalchemy.dialects import postgresql

from module_portfolio.controller import position_controller
from module_portfolio.dao.purchase_record_dao import PurchaseRecordDao
from module_portfolio.dao.redemption_record_dao import RedemptionRecordDao
from module_portfolio.entity.vo.position_vo import TransactionPageQueryModel
from module_portfolio.service.position_service import PositionService

USER_ID = 9


def compile_sql(statement) -> str:
    """编译成带字面量的 SQL 字符串,便于直接断言过滤条件与排序键。"""
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}
        )
    )


def test_purchase_side_is_scoped_and_joined():
    """买入一侧:账号过滤 + 基金名左连 + 类型字面量。"""
    sql = compile_sql(PurchaseRecordDao.build_transactions_select(USER_ID))

    assert f'purchase_records.user_id = {USER_ID}' in sql
    assert 'LEFT OUTER JOIN fund' in sql
    assert "'买入'" in sql


def test_redemption_side_keeps_soft_deleted_rows():
    """赎回一侧:同样按账号过滤,且**不过滤 del_flag**(全额赎回软删的也是历史交易)。"""
    sql = compile_sql(RedemptionRecordDao.build_transactions_select(USER_ID))

    assert f'redemption_records.user_id = {USER_ID}' in sql
    assert "'赎回'" in sql
    assert 'del_flag' not in sql


def test_page_statement_orders_and_limits_in_sql():
    """分页语句:两侧都进 union,排序键确定,分页下推到 SQL。"""
    merged = union_all(
        PurchaseRecordDao.build_transactions_select(USER_ID),
        RedemptionRecordDao.build_transactions_select(USER_ID),
    ).subquery()
    sql = compile_sql(
        select(merged)
        .order_by(
            merged.c.tx_date.desc(), merged.c.source.desc(), merged.c.record_id.desc()
        )
        .limit(10)
        .offset(20)
    )

    assert 'purchase_records' in sql and 'redemption_records' in sql
    assert 'ORDER BY' in sql
    assert sql.count('DESC') == 3  # 日期 / 来源 / 记录 id 三级稳定键
    assert 'LIMIT 10' in sql and 'OFFSET 20' in sql


def test_transaction_row_keeps_old_amount_semantics():
    """金额口径原样保留:待确认取录入金额,已确认按 份额 × 单价。"""
    pending_row = {
        'type': '买入',
        'record_id': 7,
        'source': 'purchase',
        'fund_code': '000001',
        'fund_name': '华夏成长混合',
        'tx_date': date(2026, 5, 8),
        'shares': Decimal('0'),
        'price': Decimal('0'),
        'amount': Decimal('100.00'),
        'status': '0',
        'remark': None,
    }

    assert PositionService._transaction_row(pending_row) == {
        'type': '买入',
        'record_id': 7,
        'source': 'purchase',
        'fund_code': '000001',
        'fund_name': '华夏成长混合',
        'date': '2026-05-08',
        'amount': 100.0,
        'shares': 0.0,
        'price': 0.0,
        'status': '0',
        'remark': None,
    }

    settled_row = {
        **pending_row,
        'status': '1',
        'shares': Decimal('10.5'),
        'price': Decimal('2.03'),
        'amount': None,
    }
    assert PositionService._transaction_row(settled_row)['amount'] == round(10.5 * 2.03, 2)


class _CountResult:
    def __init__(self, total: int) -> None:
        self._total = total

    def scalar(self):
        return self._total


class _RowsResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return iter(self._rows)


class _FakeSession:
    """只实现 execute:第一次是 count(取 scalar),第二次是分页列表(取 mappings)。"""

    def __init__(self, total: int = 0, rows: list[dict] | None = None) -> None:
        self.statements = []
        self._total = total
        self._rows = rows or []

    async def execute(self, statement):
        self.statements.append(statement)
        return _CountResult(self._total) if len(self.statements) == 1 else _RowsResult(self._rows)


@pytest.mark.asyncio
async def test_tx_type_purchase_skips_redemption_branch():
    """类型筛选下推到 SQL:买入档只查一张表(页面默认档就是买入)。"""
    db = _FakeSession()

    await PositionService.get_transactions_services(db, USER_ID, 1, 10, tx_type='买入')

    sql = ''.join(compile_sql(s) for s in db.statements)
    assert 'purchase_records' in sql
    assert 'redemption_records' not in sql


@pytest.mark.asyncio
async def test_unknown_tx_type_returns_empty_page_without_query():
    """未知类型:与旧实现同样返回空页,但不让 union_all 无参报错。"""
    db = _FakeSession()

    page = await PositionService.get_transactions_services(db, USER_ID, 1, 10, tx_type='全部')

    assert (page.total, page.rows) == (0, [])
    assert db.statements == []


def _bare_endpoint(endpoint):
    """剥掉 @ApiRateLimit / @Log 两层装饰(都是 functools.wraps,故可沿 __wrapped__ 循环剥到底)。"""
    while hasattr(endpoint, '__wrapped__'):
        endpoint = endpoint.__wrapped__
    return endpoint


@pytest.mark.asyncio
async def test_controller_wires_transactions_service(monkeypatch):
    """控制器 ↔ 服务接线:控制器传的关键字必须被服务接受。

    这是"只在运行时才炸"的那一层 —— 2026-09-21 删掉服务形参 `is_page` 却没改调用方,
    控制器仍传它 → 交易记录接口每次请求 500;而纯服务层用例与 ruff 都拦不住。
    故意**不 mock 服务**,让真服务真跑:关键字一旦不匹配,TypeError 当场让用例红。
    """
    monkeypatch.setattr(position_controller, '_current_user_id', lambda: USER_ID)
    db = _FakeSession()

    response = await _bare_endpoint(position_controller.get_transactions)(
        request=None,
        page_query=TransactionPageQueryModel(),
        query_db=db,
        current_user=None,
    )

    assert response is not None
    # 真的走到了新取数路径:count + 分页各一条(改成 N+1 或全量拉取就会红)
    assert len(db.statements) == 2
