"""幂等迁移脚本:清理持仓域的菜单/按钮权限记录。

背景:持仓是行级隔离的私域数据(接口一律按当前登录用户过滤,只能操作自己的
账本),按钮级权限没有安全意义只构成"登录即用"的障碍——22 个持仓接口已全部
改为仅登录(CurrentUser),入口唯一化到资产 tab 前端静态菜单(全员可见)。
管理 tab 下的 201 持仓管理页与 2101~2111 按钮记录随之失效,本脚本负责清理:
1. 删 sys_menu 中 201/2101~2111(页面与按钮记录)
2. 删 sys_role_menu 中对这些 menu_id 的角色绑定(先删关联再删主行,避免孤儿)

可重跑:目标行不存在时删除 0 行,零副作用。只碰持仓域固定 id,
基金管理(200)/净值(204)/资产配置(202)/指数(203)等其他菜单不受影响。

用法(后端根目录执行):
    .venv/bin/python scripts/migrate_portfolio_menu_cleanup.py
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

MENU_IDS = (201, 2101, 2102, 2103, 2104, 2105, 2106, 2107, 2108, 2109, 2110, 2111)
ID_LIST = ', '.join(str(i) for i in MENU_IDS)

DELETE_ROLE_MENU_SQL = f'DELETE FROM sys_role_menu WHERE menu_id IN ({ID_LIST})'
DELETE_MENU_SQL = f'DELETE FROM sys_menu WHERE menu_id IN ({ID_LIST})'


async def main() -> None:
    engine = create_async_engine(DataBaseConfig.async_url)
    async with engine.begin() as conn:
        rm_result = await conn.execute(text(DELETE_ROLE_MENU_SQL))
        print(f'[清理] ① 角色菜单关联删除 {rm_result.rowcount} 行')
        menu_result = await conn.execute(text(DELETE_MENU_SQL))
        print(f'[清理] ② 菜单记录删除 {menu_result.rowcount} 行(首次应 12 行,重跑 0 行)')
    await engine.dispose()
    print('[清理] 完成;持仓域接口已仅登录,入口在资产 tab 前端静态菜单(全员可见)')


if __name__ == '__main__':
    asyncio.run(main())
