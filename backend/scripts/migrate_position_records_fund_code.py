"""幂等迁移脚本:买入/赎回记录表加 fund_code(第三列)。

背景:持仓明细改按基金代码匹配买卖记录(同基金清仓后再买会换新持仓行,
按 position_id 外键会令历史断档)。本脚本按「建新表 → 按 position_id 回填
fund_code 拷数据 → 删旧表 → 改名」重建两张表,把 fund_code 放到第三列
(purchase_id/redemption_id 之后)。单事务执行,失败自动回滚,存量数据零损失。

回填规则:LEFT JOIN user_fund_positions 按 position_id 取 fund_code;
持仓被物理删除的孤儿记录(Excel 导入清空重建场景)回填为空串兜底,脚本会打印行数。

全部可重跑(重复执行无副作用):
- 表不存在(全新库) → 交给建表流程,直接退出
- 两表 fund_code 的 ordinal_position 已是期望位置(第 3 列) → 打印「已就绪」直接退出
- 否则仅重建未就绪的表

列定义与 purchase_record_do.py / redemption_record_do.py / db/base_model.py
逐字段对齐(del_flag 带 server_default;审计五列无 server_default,由 ORM 端填充)。

用法(后端根目录执行):
    .venv/bin/python scripts/migrate_position_records_fund_code.py
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

EXPECTED_ORDINAL = 3

# 每张表的重建定义:fund_code 由 position_id LEFT JOIN 持仓表回填
TABLE_DEFS = {
    'purchase_records': {
        'pk': 'purchase_id',
        'create_new': """
CREATE TABLE purchase_records_new (
    purchase_id   BIGSERIAL PRIMARY KEY,
    position_id   INTEGER NOT NULL,
    fund_code     VARCHAR(20) NOT NULL,
    shares        NUMERIC(18, 4) NOT NULL,
    cost_price    NUMERIC(18, 4) NOT NULL,
    purchase_date DATE NOT NULL,
    create_by     VARCHAR(64) DEFAULT '',
    create_time   TIMESTAMP,
    update_by     VARCHAR(64) DEFAULT '',
    update_time   TIMESTAMP,
    remark        VARCHAR(500) DEFAULT ''
)
""",
        'copy': """
INSERT INTO purchase_records_new
    (purchase_id, position_id, fund_code, shares, cost_price, purchase_date,
     create_by, create_time, update_by, update_time, remark)
SELECT p.purchase_id, p.position_id,
       COALESCE(u.fund_code, ''),
       p.shares, p.cost_price, p.purchase_date,
       p.create_by, p.create_time, p.update_by, p.update_time, p.remark
FROM purchase_records p
LEFT JOIN user_fund_positions u ON u.position_id = p.position_id
ORDER BY p.purchase_id
""",
        'sequence': """
SELECT setval(
    pg_get_serial_sequence('purchase_records_new', 'purchase_id'),
    (SELECT COALESCE(MAX(purchase_id), 0) FROM purchase_records_new) + 1,
    false
)
""",
        'table_comment': "COMMENT ON TABLE purchase_records_new IS '基金买入记录表'",
        'column_comments': [
            ('purchase_id', '买入记录主键'),
            ('position_id', '持仓ID(逻辑关联 user_fund_positions)'),
            ('fund_code', '基金代码(明细按基金代码匹配,跨持仓合并历史)'),
            ('shares', '买入份额(=购买金额/买入日单位净值)'),
            ('cost_price', '买入成本单价(买入日单位净值)'),
            ('purchase_date', '买入日期'),
            ('create_by', '创建者'),
            ('create_time', '创建时间'),
            ('update_by', '更新者'),
            ('update_time', '更新时间'),
            ('remark', '备注'),
        ],
        'indexes': [
            'CREATE INDEX idx_purchase_position ON purchase_records (position_id)',
            'CREATE INDEX idx_purchase_fund ON purchase_records (fund_code)',
        ],
    },
    'redemption_records': {
        'pk': 'redemption_id',
        'create_new': """
CREATE TABLE redemption_records_new (
    redemption_id   BIGSERIAL PRIMARY KEY,
    position_id     INTEGER NOT NULL,
    fund_code       VARCHAR(20) NOT NULL,
    shares          NUMERIC(18, 4) NOT NULL,
    nav_price       NUMERIC(18, 4) NOT NULL,
    redemption_date DATE NOT NULL,
    del_flag        CHAR(1) DEFAULT '0',
    create_by       VARCHAR(64) DEFAULT '',
    create_time     TIMESTAMP,
    update_by       VARCHAR(64) DEFAULT '',
    update_time     TIMESTAMP,
    remark          VARCHAR(500) DEFAULT ''
)
""",
        'copy': """
INSERT INTO redemption_records_new
    (redemption_id, position_id, fund_code, shares, nav_price, redemption_date,
     del_flag, create_by, create_time, update_by, update_time, remark)
SELECT r.redemption_id, r.position_id,
       COALESCE(u.fund_code, ''),
       r.shares, r.nav_price, r.redemption_date, r.del_flag,
       r.create_by, r.create_time, r.update_by, r.update_time, r.remark
FROM redemption_records r
LEFT JOIN user_fund_positions u ON u.position_id = r.position_id
ORDER BY r.redemption_id
""",
        'sequence': """
SELECT setval(
    pg_get_serial_sequence('redemption_records_new', 'redemption_id'),
    (SELECT COALESCE(MAX(redemption_id), 0) FROM redemption_records_new) + 1,
    false
)
""",
        'table_comment': "COMMENT ON TABLE redemption_records_new IS '基金赎回记录表'",
        'column_comments': [
            ('redemption_id', '赎回记录主键'),
            ('position_id', '持仓ID(逻辑关联 user_fund_positions)'),
            ('fund_code', '基金代码(明细按基金代码匹配,跨持仓合并历史)'),
            ('shares', '赎回份额'),
            ('nav_price', '赎回净值(赎回日单位净值)'),
            ('redemption_date', '赎回日期'),
            ('del_flag', '删除标志(0存在 2删除)'),
            ('create_by', '创建者'),
            ('create_time', '创建时间'),
            ('update_by', '更新者'),
            ('update_time', '更新时间'),
            ('remark', '备注'),
        ],
        'indexes': [
            'CREATE INDEX idx_redemption_position ON redemption_records (position_id)',
            'CREATE INDEX idx_redemption_fund ON redemption_records (fund_code)',
        ],
    },
}

FUND_CODE_ORDINAL_SQL = """
SELECT ordinal_position FROM information_schema.columns
WHERE table_name = :table_name AND column_name = 'fund_code'
"""


async def rebuild_table(conn, table: str, definition: dict) -> None:
    """重建单张表:建 _new → 回填拷数据 → 序列对齐 → 删旧表改名 → 索引/注释。"""
    print(f'[迁移] {table}:fund_code 不在第 {EXPECTED_ORDINAL} 列,开始重建')

    await conn.execute(text(definition['create_new']))
    copied = (await conn.execute(text(definition['copy']))).rowcount
    print(f'[迁移] {table}:数据拷贝完成,{copied} 行(fund_code 已按 position_id 回填)')

    await conn.execute(text(definition['sequence']))
    await conn.execute(text(definition['table_comment']))
    for column, comment in definition['column_comments']:
        await conn.execute(
            text(f"COMMENT ON COLUMN {table}_new.{column} IS '{comment}'")
        )
    print(f'[迁移] {table}:序列对齐 + 表列注释重建完成')

    # 索引名 schema 内全局唯一,必须等旧表(带着旧索引)删除后再建
    await conn.execute(text(f'DROP TABLE {table}'))
    await conn.execute(text(f'ALTER TABLE {table}_new RENAME TO {table}'))
    print(f'[迁移] {table}:旧表已删,新表改名完成')

    for index_sql in definition['indexes']:
        await conn.execute(text(index_sql))
    print(f'[迁移] {table}:索引重建完成({", ".join(i.split("ON ")[1] for i in definition["indexes"])})')


async def main() -> None:
    if DataBaseConfig.db_type != 'postgresql':
        print(f'[迁移] 当前数据库类型 {DataBaseConfig.db_type} 不支持本脚本语法,终止')
        return

    engine = create_async_engine(DataBaseConfig.async_url)
    async with engine.begin() as conn:
        for table, definition in TABLE_DEFS.items():
            table_exists = (
                await conn.execute(text(f"SELECT to_regclass('{table}') IS NOT NULL"))
            ).scalar()
            if not table_exists:
                print(f'[迁移] {table} 表不存在(全新库),交给建表流程,跳过')
                continue

            ordinal = (
                await conn.execute(
                    text(FUND_CODE_ORDINAL_SQL), {'table_name': table}
                )
            ).scalar()
            if ordinal == EXPECTED_ORDINAL:
                print(f'[迁移] {table}:fund_code 列序已就绪(第 {ordinal} 列),跳过')
                continue
            await rebuild_table(conn, table, definition)

    await engine.dispose()
    print('[迁移] 完成;重启后端生效(明细改按 fund_code 匹配,跨持仓历史不断档)')
    print(r"[迁移] 校验:psql 里 \d purchase_records / \d redemption_records 确认列序与索引")


if __name__ == '__main__':
    asyncio.run(main())
