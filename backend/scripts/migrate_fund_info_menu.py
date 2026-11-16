"""一次性迁移:管理域新增「基金信息管理」菜单(2026-10-12)。

背景:fund_info 三级缓存在 DB 命中后不再回源,档案数据停在首次抓取的快照;
新增管理页(基金信息管理)提供同步/新增/删除,需配菜单与按钮权限。

幂等:按 menu_id 判存在,已存在跳过;admin 角色绑定新菜单行;最后同步 pg
序列到 max(menu_id)(种子 menu_id 手工指定,不推序列则自增 INSERT 撞主键)。
执行顺序硬约束:先跑本脚本再重启后端(端点权限 fund:info:* 依赖菜单行)。

用法:.venv/bin/python scripts/migrate_fund_info_menu.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text  # noqa: E402

from db.database import async_engine  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from module_system.entity.do.menu_do import SysMenu  # noqa: E402

# (menu_id, menu_name, parent_id, order_num, menu_type, path, component, perms, icon)
ROWS = [
    (105, '基金信息管理', 2, 5, 'C', '/app/asset/fund-info-management', 'asset/fund-info-management', 'fund:info:list', 'database'),
    (1051, '基金信息同步', 105, 1, 'F', None, None, 'fund:info:sync', None),
    (1052, '基金信息新增', 105, 2, 'F', None, None, 'fund:info:add', None),
    (1053, '基金信息删除', 105, 3, 'F', None, None, 'fund:info:remove', None),
]


async def main() -> None:
    from sqlalchemy.orm import sessionmaker

    session_maker = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as db:
        inserted = 0
        for menu_id, name, parent_id, order_num, mtype, path, component, perms, icon in ROWS:
            exists = (
                await db.execute(select(SysMenu).where(SysMenu.menu_id == menu_id))
            ).scalars().first()
            if exists:
                # 已存在则校正挂载(幂等 upsert:2026-10-12 曾挂错到系统管理目录下)
                exists.parent_id = parent_id
                exists.order_num = order_num
                exists.path = path
                exists.component = component
                exists.perms = perms
                continue
            db.add(
                SysMenu(
                    menu_id=menu_id,
                    menu_name=name,
                    parent_id=parent_id,
                    order_num=order_num,
                    menu_type=mtype,
                    path=path,
                    component=component,
                    perms=perms,
                    icon=icon,
                    visible='0',
                    status='0',
                )
            )
            inserted += 1
        await db.flush()
        role_row = (
            await db.execute(text("SELECT role_id FROM sys_role WHERE role_key = 'admin'"))
        ).first()
        if role_row:
            for menu_id, *_ in ROWS:
                bound = (
                    await db.execute(
                        text('SELECT 1 FROM sys_role_menu WHERE role_id = :rid AND menu_id = :mid'),
                        {'rid': role_row.role_id, 'mid': menu_id},
                    )
                ).first()
                if not bound:
                    await db.execute(
                        text('INSERT INTO sys_role_menu (role_id, menu_id) VALUES (:rid, :mid)'),
                        {'rid': role_row.role_id, 'mid': menu_id},
                    )
        await db.commit()
        await db.execute(
            text(
                "SELECT setval('sys_menu_menu_id_seq', GREATEST((SELECT max(menu_id) FROM sys_menu), 1))"
            )
        )
        await db.commit()
        print(f'插入 {inserted} 行;admin 绑定已补;序列已同步')


if __name__ == '__main__':
    asyncio.run(main())
