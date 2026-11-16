"""交易待确认机制迁移:purchase_records / redemption_records 加 status 与 amount 列。

背景:净值 T+1 发布,交易日 15 点后/周末录入的交易在录入时刻拿不到所选日期的净值,
旧逻辑会错误地回落「取最新值」立即算份额。改造后这类交易落库为 status='0'(待确认),
份额不计算、不计入收益体系;目标净值日发布后由读取路径懒确认回填并置 status='1'。

幂等:列已存在即跳过,可重复执行。存量行 status 由 server_default='1'(已确认)、
amount 回填为 shares×单价,语义与迁移前完全一致。

用法: .venv/bin/python scripts/migrate_trade_confirm_status.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv('.env.dev')

from sqlalchemy import text  # noqa: E402

from config.settings import DataBaseConfig  # noqa: E402

# (表名, 金额回填表达式)——amount 由既有列运算回填,与迁移前数值完全一致
TABLES = [
    ('purchase_records', 'shares * cost_price'),
    ('redemption_records', 'shares * nav_price'),
]

COLUMN_EXISTS_SQL = """
SELECT 1 FROM information_schema.columns
WHERE table_name = :table AND column_name = :column
"""


async def table_exists(conn, table: str) -> bool:
    return (await conn.execute(text(f"SELECT to_regclass('{table}') IS NOT NULL"))).scalar()


async def column_exists(conn, table: str, column: str) -> bool:
    result = await conn.execute(
        text(COLUMN_EXISTS_SQL), {'table': table, 'column': column}
    )
    return result.scalar() is not None


async def main() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(DataBaseConfig.async_url)
    async with engine.begin() as conn:
        for table, amount_expr in TABLES:
            if not await table_exists(conn, table):
                print(f'[跳过] {table} 不存在(交由建表流程创建)')
                continue

            if not await column_exists(conn, table, 'status'):
                await conn.execute(
                    text(
                        f"ALTER TABLE {table} ADD COLUMN status CHAR(1) "
                        f"NOT NULL DEFAULT '1'"
                    )
                )
                await conn.execute(
                    text(
                        f"COMMENT ON COLUMN {table}.status IS "
                        f"'确认状态 0待确认 1已确认 - 净值T+1发布前录入的交易待目标净值日公布后回填'"
                    )
                )
                print(f'[完成] {table} 加列 status')
            else:
                print(f'[跳过] {table}.status 已存在')

            if not await column_exists(conn, table, 'amount'):
                await conn.execute(
                    text(f'ALTER TABLE {table} ADD COLUMN amount NUMERIC(18, 2) NULL')
                )
                # 存量回填:已确认口径的金额 = 份额 × 成交单价
                await conn.execute(
                    text(f'UPDATE {table} SET amount = {amount_expr}')
                )
                print(f'[完成] {table} 加列 amount 并回填存量')
            else:
                print(f'[跳过] {table}.amount 已存在')

    await engine.dispose()
    print('迁移结束')


if __name__ == '__main__':
    asyncio.run(main())
