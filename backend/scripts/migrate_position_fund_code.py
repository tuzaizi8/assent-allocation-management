"""幂等迁移脚本:持仓头表关联键切换(fund_id → fund_code)。

背景:user_fund_positions 与 fund 表本就无数据库级外键(仅"逻辑关联"注释)。
持仓以基金代码定位与以 ID 定位等价(fund.code 全局唯一,含已删记录),
且免去"先查基金拿 ID 再建仓"的二次查询。本脚本做四件事(全部可重跑,重复执行无副作用):
1. 加 fund_code 列(IF NOT EXISTS,先可空)
2. 存量回填:按 fund.fund_id = user_fund_positions.fund_id 回填 code(仅更新 NULL 行)
3. fund_code 置 NOT NULL + 索引 idx_position_user_fund 重建为 (user_id, fund_code)
4. 删除 fund_id 列(回填有未命中行则中止不删,存量零损失)

执行顺序强约束:先跑本脚本,再重启后端——旧代码依赖 fund_id 列,
代码先上线而库未迁移会直接崩。

用法(后端根目录执行):
    .venv/bin/python scripts/migrate_position_fund_code.py
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

# 回填用 PG 的 UPDATE...FROM、探测用 information_schema,均不兼容 MySQL
ADD_COLUMN_SQL = """
ALTER TABLE user_fund_positions ADD COLUMN IF NOT EXISTS fund_code VARCHAR(20)
"""

BACKFILL_SQL = """
UPDATE user_fund_positions p
SET fund_code = f.code
FROM fund f
WHERE p.fund_id = f.fund_id
  AND p.fund_code IS NULL
"""

UNMATCHED_SQL = "SELECT COUNT(*) FROM user_fund_positions WHERE fund_code IS NULL"
SET_NOT_NULL_SQL = "ALTER TABLE user_fund_positions ALTER COLUMN fund_code SET NOT NULL"
DROP_OLD_INDEX_SQL = "DROP INDEX IF EXISTS idx_position_user_fund"
CREATE_NEW_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_position_user_fund "
    "ON user_fund_positions (user_id, fund_code)"
)
DROP_FUND_ID_SQL = "ALTER TABLE user_fund_positions DROP COLUMN IF EXISTS fund_id"

TABLE_EXISTS_SQL = "SELECT to_regclass('user_fund_positions') IS NOT NULL"
# fund_id 列还在才需要回填/删列;已删过(重跑)则整段跳过
FUND_ID_EXISTS_SQL = """
SELECT 1 FROM information_schema.columns
WHERE table_name = 'user_fund_positions' AND column_name = 'fund_id'
"""


async def main() -> None:
    if DataBaseConfig.db_type != 'postgresql':
        print(f'[迁移] 当前数据库类型 {DataBaseConfig.db_type} 不支持本脚本语法,终止')
        return

    engine = create_async_engine(DataBaseConfig.async_url)
    async with engine.begin() as conn:
        table_exists = (await conn.execute(text(TABLE_EXISTS_SQL))).scalar()
        if not table_exists:
            print('[迁移] user_fund_positions 表不存在(全新库),无需迁移,交给建表流程')
            await engine.dispose()
            return

        await conn.execute(text(ADD_COLUMN_SQL))
        print('[迁移] ① fund_code 列已就绪(IF NOT EXISTS)')

        has_fund_id = (await conn.execute(text(FUND_ID_EXISTS_SQL))).scalar() is not None
        if has_fund_id:
            result = await conn.execute(text(BACKFILL_SQL))
            print(f'[迁移] ② 存量回填完成,更新 {result.rowcount} 行(空表/新库为 0 属正常)')

            unmatched = (await conn.execute(text(UNMATCHED_SQL))).scalar() or 0
            if unmatched > 0:
                print(
                    f'[迁移] 中止:{unmatched} 行未能按 fund_id 匹配到基金代码,'
                    'fund_id 列保留(存量零损失),请人工核对这些行后修复数据再重跑'
                )
                await engine.dispose()
                return
            print('[迁移] ③ 回填零未命中')
        else:
            print('[迁移] ②③ fund_id 列已不存在(此前迁移过),跳过回填')

        await conn.execute(text(SET_NOT_NULL_SQL))
        await conn.execute(text(DROP_OLD_INDEX_SQL))
        await conn.execute(text(CREATE_NEW_INDEX_SQL))
        print('[迁移] ④ NOT NULL + 索引重建为 (user_id, fund_code) 完成')

        if has_fund_id:
            await conn.execute(text(DROP_FUND_ID_SQL))
            print('[迁移] ⑤ fund_id 列已删除')

    await engine.dispose()
    print('[迁移] 完成;请重启后端使新代码生效(旧代码依赖 fund_id 列)')


if __name__ == '__main__':
    asyncio.run(main())
