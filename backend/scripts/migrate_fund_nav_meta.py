"""幂等迁移脚本:基金净值表元数据列。

两件事(全部可重跑,重复执行无副作用):
1. fund_nav_history 加 latest_date/record_count 两列(IF NOT EXISTS——列表页窄投影
   与三态同步状态 SQL 谓词依赖它们,读路径因此不必解析 nav_data 大 JSON)
2. 存量回填:从 nav_data JSON 提取最新净值日期与记录条数(仅更新 NULL 行,零损失;
   新同步的行由 upsert_nav_history 写路径维护,不经过这里)

菜单 204/2041/2042 不在本脚本处理:init_data 的渐进补种(按 menu_id 幂等补插
+ admin role_key 通配可见)会在后端启动时自动完成。

用法(后端根目录执行):
    .venv/bin/python scripts/migrate_fund_nav_meta.py
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

# 回填依赖 PG 的 json 数组函数(json_array_length/按索引取末元素),MySQL 不兼容
ADD_COLUMNS_SQL = """
ALTER TABLE fund_nav_history
    ADD COLUMN IF NOT EXISTS latest_date DATE,
    ADD COLUMN IF NOT EXISTS record_count INTEGER
"""

BACKFILL_SQL = """
UPDATE fund_nav_history
SET record_count = json_array_length(nav_data->'records'),
    latest_date = ((nav_data->'records'->(json_array_length(nav_data->'records') - 1))->>'nav_date')::date
WHERE latest_date IS NULL
  AND nav_data IS NOT NULL
  AND json_array_length(nav_data->'records') > 0
"""


async def main() -> None:
    if DataBaseConfig.db_type != 'postgresql':
        print(f'[迁移] 当前数据库类型 {DataBaseConfig.db_type} 不支持本脚本的 json 函数,终止')
        return

    engine = create_async_engine(DataBaseConfig.async_url)
    async with engine.begin() as conn:
        await conn.execute(text(ADD_COLUMNS_SQL))
        print('[迁移] ① latest_date/record_count 两列已就绪(IF NOT EXISTS)')

        result = await conn.execute(text(BACKFILL_SQL))
        print(f'[迁移] ② 存量回填完成,更新 {result.rowcount} 行(空表/新库为 0 属正常)')

    await engine.dispose()
    print('[迁移] 完成;菜单 204/2041/2042 由后端启动时的渐进补种自动插入,记得重启后端并重新登录')


if __name__ == '__main__':
    asyncio.run(main())
