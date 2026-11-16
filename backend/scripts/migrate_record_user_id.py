"""幂等迁移脚本:给买卖流水表补「所属账号」列(purchase_records / redemption_records 加 user_id)。

背景:两张流水表原先只有 position_id(逻辑关联 user_fund_positions),归属只能靠持仓行推断。
而「清空持仓」会物理删掉持仓行却刻意保留流水 → 那批流水从此既无法归属、也无法按账号删除
(2026-09-21 使用者报的「僵尸数据」);同时「持仓详情」按 fund_code 全库查流水,两个账号买
同一只基金时会互相串数据。故加 user_id,读写删全部按账号走。

全部可重跑(重复执行无副作用):
- 表不存在(全新库) → 交给启动时的 create_all 建表流程,直接退出
- user_id 列已存在 → 打印「已就绪」直接退出
否则:加列(先可空) → 按 position_id 回填 → 统计 NULL
  - NULL = 0 → SET NOT NULL(把「靠约定」变成「数据库约束」)
  - NULL > 0 → 不置 NOT NULL,打印行数与清理建议(宁可保留可空,也不猜一个归属写进去)
→ 建 (user_id, fund_code) 复合索引 → 补列注释。全程单事务,失败自动回滚。

已知取舍:ADD COLUMN 会让存量库的 user_id 落在表尾,与 DO 声明顺序(紧跟 position_id 之后)
有外观漂移 —— 不影响任何逻辑;如需严格对齐列序,照 scripts/migrate_position_column_order.py
那样重建表(多约 150 行,收益仅是列序美观)。

回滚(表名替换即可,可逆;回滚后代码需一并回到加列前的版本):
    DROP INDEX IF EXISTS idx_purchase_user_fund;
    ALTER TABLE purchase_records DROP COLUMN IF EXISTS user_id;

用法(后端根目录执行):
    .venv/bin/python scripts/migrate_record_user_id.py
"""

import asyncio
import sys
from pathlib import Path

# 以脚本方式直接执行时 sys.path[0] 是 scripts/ 而不是项目根,
# 补上项目根才能导入 config ——否则只有用 -m 方式运行才找得到
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

load_dotenv('.env.dev')

# 以下导入必须在 load_dotenv 之后:配置类实例化时就要读到环境变量
from config.settings import DataBaseConfig  # noqa: E402

POSITIONS_TABLE = 'user_fund_positions'
COLUMN_COMMENT = '用户ID(逻辑关联 sys_user.user_id)'

# (表名, 中文名, 复合索引名) —— 两张表同构,一份声明驱动全部语句
RECORD_TABLES = [
    ('purchase_records', '买入流水', 'idx_purchase_user_fund'),
    ('redemption_records', '赎回流水', 'idx_redemption_user_fund'),
]


async def table_exists(conn, table: str) -> bool:
    result = await conn.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {'t': table})
    return bool(result.scalar())


async def has_column(conn, table: str, column: str) -> bool:
    result = await conn.execute(
        text(
            'SELECT count(*) FROM information_schema.columns '
            "WHERE table_name = :t AND column_name = :c"
        ),
        {'t': table, 'c': column},
    )
    return bool(result.scalar())


async def migrate_table(conn, table: str, label: str, index_name: str) -> None:
    if not await table_exists(conn, table):
        print(f'[迁移] {table} 不存在(全新库),交给 create_all 建表流程')
        return
    if await has_column(conn, table, 'user_id'):
        print(f'[迁移] {table}.user_id 已就绪,无需迁移')
        return

    total = (await conn.execute(text(f'SELECT count(*) FROM {table}'))).scalar()
    print(f'[迁移] {label}:① {table} 加列 user_id(现有 {total} 行)')
    await conn.execute(text(f'ALTER TABLE {table} ADD COLUMN user_id INTEGER'))

    if await table_exists(conn, POSITIONS_TABLE):
        backfilled = (
            await conn.execute(
                text(
                    f'UPDATE {table} r SET user_id = p.user_id '
                    f'FROM {POSITIONS_TABLE} p '
                    'WHERE r.position_id = p.position_id AND r.user_id IS NULL'
                )
            )
        ).rowcount
    else:
        backfilled = 0
        print(f'[迁移] {label}:② 持仓表不存在,跳过回填(整表都算无主)')
    print(f'[迁移] {label}:② 回填 {backfilled} 行(按 position_id 找归属)')

    orphan = (
        await conn.execute(text(f'SELECT count(*) FROM {table} WHERE user_id IS NULL'))
    ).scalar()
    if orphan:
        print(
            f'[迁移] {label}:③ 有 {orphan} 行无法归属(持仓行已不在表里),保留可空、不置 NOT NULL;'
            '请按知识库「无主流水自检/清理」处理后重跑本脚本'
        )
    else:
        await conn.execute(text(f'ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL'))
        print(f'[迁移] {label}:③ 无残留 → user_id 置为 NOT NULL')

    await conn.execute(
        text(f'CREATE INDEX IF NOT EXISTS {index_name} ON {table} (user_id, fund_code)')
    )
    await conn.execute(text(f"COMMENT ON COLUMN {table}.user_id IS '{COLUMN_COMMENT}'"))
    print(f'[迁移] {label}:④ 复合索引 {index_name}(user_id, fund_code) 与列注释完成')


async def main() -> None:
    if DataBaseConfig.db_type != 'postgresql':
        print(f'[迁移] 当前数据库类型 {DataBaseConfig.db_type} 不支持本脚本语法,终止')
        return

    engine = create_async_engine(DataBaseConfig.async_url)
    async with engine.begin() as conn:
        for table, label, index_name in RECORD_TABLES:
            await migrate_table(conn, table, label, index_name)

    await engine.dispose()
    print('[迁移] 完成;可直接重启后端(读写已按账号走,旧代码不依赖本列,回滚见脚本头注释)')
    print('[迁移] 校验:psql 里 \\d purchase_records / \\d redemption_records 确认 user_id 非空与复合索引')


if __name__ == '__main__':
    asyncio.run(main())
