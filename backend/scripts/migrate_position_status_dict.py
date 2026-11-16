"""幂等迁移脚本:持仓状态值编码化(中文 → 字典 sys_position_status 的编码)。

背景:持仓状态接入字典管理(dict_value '0'正常/'1'部分赎回/'2'全部赎回),
存量行 status 存的是中文,需刷成编码。只改值不删行,零损失;
各句自带 WHERE 旧值条件,重复执行无副作用。

执行顺序建议:先跑本脚本,再重启后端——新代码按编码写入/筛选,
存量中文值在迁移前会被前端状态徽章显示为兜底文案「未知」。

用法(后端根目录执行):
    .venv/bin/python scripts/migrate_position_status_dict.py
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

# (旧中文值 → 字典编码),与 position_do 的状态常量逐字对应
STATUS_MIGRATIONS = [
    ('正常', '0'),
    ('部分赎回', '1'),
    ('全部赎回', '2'),
]

RESIDUAL_SQL = "SELECT COUNT(*) FROM user_fund_positions WHERE status NOT IN ('0', '1', '2')"


async def main() -> None:
    if DataBaseConfig.db_type != 'postgresql':
        print(f'[迁移] 当前数据库类型 {DataBaseConfig.db_type} 不支持本脚本语法,终止')
        return

    engine = create_async_engine(DataBaseConfig.async_url)
    async with engine.begin() as conn:
        for old_value, code in STATUS_MIGRATIONS:
            result = await conn.execute(
                text('UPDATE user_fund_positions SET status = :code WHERE status = :old'),
                {'code': code, 'old': old_value},
            )
            print(f'[迁移] ① 「{old_value}」→「{code}」:{result.rowcount} 行(0 属正常)')

        residual = (await conn.execute(text(RESIDUAL_SQL))).scalar() or 0
        if residual > 0:
            print(f'[迁移] 告警:{residual} 行 status 不在编码集内(不影响本次迁移,请人工核对)')
        else:
            print('[迁移] ② 无残留旧值,状态列已全部编码化')

    await engine.dispose()
    print('[迁移] 完成;请重启后端并确认字典已渐进补种(日志含种子字典补种输出)')


if __name__ == '__main__':
    asyncio.run(main())
