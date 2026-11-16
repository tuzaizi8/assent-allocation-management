"""流水归属隔离的最小回归:按基金查流水必须同时按账号过滤,清空流水必须按账号删。

不连库:用假 session 捕获 SQLAlchemy 语句并编译成字符串,断言 WHERE 条件 —— 少一个 user_id,
两个账号买同一只基金时就会把对方的流水混进来(2026-09-21 修的那个跨账号串数据)。
"""

import pytest
from sqlalchemy.dialects import postgresql

from module_portfolio.dao.purchase_record_dao import PurchaseRecordDao
from module_portfolio.dao.redemption_record_dao import RedemptionRecordDao

USER_ID = 7
FUND_CODE = '000001'


class _Result:
    """DAO 只用到 rowcount / scalars().all() 这几个动作,空结果即可。"""

    rowcount = 0

    def scalars(self):
        return self

    def all(self):
        return []


class _CapturingSession:
    """不连库的假会话:记下每条语句,返回空结果。"""

    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result()


def compile_sql(statement) -> str:
    """编译成带字面量的 SQL 字符串,便于直接断言过滤条件。"""
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}
        )
    )


@pytest.mark.asyncio
async def test_records_by_fund_is_scoped_to_user():
    """按基金查流水:必须同时带 user_id 与 fund_code。"""
    db = _CapturingSession()

    await PurchaseRecordDao.get_purchase_records_by_fund(db, USER_ID, FUND_CODE)
    await RedemptionRecordDao.get_redemption_records_by_fund(db, USER_ID, FUND_CODE)

    purchase_sql, redemption_sql = (compile_sql(s) for s in db.statements)
    assert f'purchase_records.user_id = {USER_ID}' in purchase_sql
    assert f"purchase_records.fund_code = '{FUND_CODE}'" in purchase_sql
    assert f'redemption_records.user_id = {USER_ID}' in redemption_sql
    assert f"redemption_records.fund_code = '{FUND_CODE}'" in redemption_sql


@pytest.mark.asyncio
async def test_clear_all_records_deletes_by_user():
    """清空全部流水:按 user_id 删,不再依赖持仓 ID(先清空持仓后的残留也删得掉)。"""
    db = _CapturingSession()

    await PurchaseRecordDao.delete_all_for_user(db, USER_ID)
    await RedemptionRecordDao.delete_all_for_user(db, USER_ID)

    purchase_sql, redemption_sql = (compile_sql(s) for s in db.statements)
    assert purchase_sql.startswith('DELETE FROM purchase_records')
    assert f'purchase_records.user_id = {USER_ID}' in purchase_sql
    assert 'position_id' not in purchase_sql
    assert 'position_id' not in redemption_sql
