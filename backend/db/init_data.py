"""种子数据初始化。

应用启动时(lifespan)按表分别判空插入种子:用户/角色/菜单/关联各自独立幂等,
支持存量环境渐进补种(如已有 admin 的环境补插 RBAC 种子)。
"""

from datetime import datetime

from sqlalchemy import func, select, text

from config.settings import DataBaseConfig
from db.database import AsyncSessionLocal
from module_system.entity.do.menu_do import SysMenu
from module_system.entity.do.role_do import SysRole, SysRoleMenu
from module_system.entity.do.user_do import SysUser, SysUserRole
from module_system.entity.do.dict_do import SysDictData, SysDictType
from utils.log import logger
from utils.pwd_util import PwdUtil

# 种子账号(联调凭证;email 用 .local 占位域,避免与任何线上真实账号重合)
SEED_ADMIN_EMAIL = 'admin@assent.local'
SEED_ADMIN_PASSWORD = 'password123'

# 种子菜单清单(menu_id 分段:1=目录 100+=菜单 1000+=按钮)
SEED_MENUS = [
    SysMenu(menu_id=1, menu_name='系统管理', parent_id=0, order_num=1, menu_type='M', path='/app/system', icon='settings', visible='0', status='0'),
    SysMenu(menu_id=100, menu_name='用户管理', parent_id=1, order_num=1, menu_type='C', path='/app/system/users', component='system/users', perms='system:user:list', icon='users', visible='0', status='0'),
    SysMenu(menu_id=1001, menu_name='用户查询', parent_id=100, order_num=1, menu_type='F', perms='system:user:query', visible='0', status='0'),
    SysMenu(menu_id=1002, menu_name='用户新增', parent_id=100, order_num=2, menu_type='F', perms='system:user:add', visible='0', status='0'),
    SysMenu(menu_id=1003, menu_name='用户修改', parent_id=100, order_num=3, menu_type='F', perms='system:user:edit', visible='0', status='0'),
    SysMenu(menu_id=1004, menu_name='用户删除', parent_id=100, order_num=4, menu_type='F', perms='system:user:remove', visible='0', status='0'),
    # 菜单管理/角色管理页 + 各 4 个操作按钮
    SysMenu(menu_id=101, menu_name='菜单管理', parent_id=1, order_num=2, menu_type='C', path='/app/system/menus', component='system/menus', perms='system:menu:list', icon='menu', visible='0', status='0'),
    SysMenu(menu_id=1101, menu_name='菜单查询', parent_id=101, order_num=1, menu_type='F', perms='system:menu:query', visible='0', status='0'),
    SysMenu(menu_id=1102, menu_name='菜单新增', parent_id=101, order_num=2, menu_type='F', perms='system:menu:add', visible='0', status='0'),
    SysMenu(menu_id=1103, menu_name='菜单修改', parent_id=101, order_num=3, menu_type='F', perms='system:menu:edit', visible='0', status='0'),
    SysMenu(menu_id=1104, menu_name='菜单删除', parent_id=101, order_num=4, menu_type='F', perms='system:menu:remove', visible='0', status='0'),
    SysMenu(menu_id=102, menu_name='角色管理', parent_id=1, order_num=3, menu_type='C', path='/app/system/roles', component='system/roles', perms='system:role:list', icon='shield', visible='0', status='0'),
    SysMenu(menu_id=1201, menu_name='角色查询', parent_id=102, order_num=1, menu_type='F', perms='system:role:query', visible='0', status='0'),
    SysMenu(menu_id=1202, menu_name='角色新增', parent_id=102, order_num=2, menu_type='F', perms='system:role:add', visible='0', status='0'),
    SysMenu(menu_id=1203, menu_name='角色修改', parent_id=102, order_num=3, menu_type='F', perms='system:role:edit', visible='0', status='0'),
    SysMenu(menu_id=1204, menu_name='角色删除', parent_id=102, order_num=4, menu_type='F', perms='system:role:remove', visible='0', status='0'),
    # 字典管理页 + 4 个操作按钮
    SysMenu(menu_id=103, menu_name='字典管理', parent_id=1, order_num=4, menu_type='C', path='/app/system/dicts', component='system/dicts', perms='system:dict:list', icon='list', visible='0', status='0'),
    SysMenu(menu_id=1301, menu_name='字典查询', parent_id=103, order_num=1, menu_type='F', perms='system:dict:query', visible='0', status='0'),
    SysMenu(menu_id=1302, menu_name='字典新增', parent_id=103, order_num=2, menu_type='F', perms='system:dict:add', visible='0', status='0'),
    SysMenu(menu_id=1303, menu_name='字典修改', parent_id=103, order_num=3, menu_type='F', perms='system:dict:edit', visible='0', status='0'),
    SysMenu(menu_id=1304, menu_name='字典删除', parent_id=103, order_num=4, menu_type='F', perms='system:dict:remove', visible='0', status='0'),
    # 日志管理页(只读查询,无操作按钮种子)
    SysMenu(menu_id=104, menu_name='日志管理', parent_id=1, order_num=5, menu_type='C', path='/app/system/logs', component='system/logs', perms='system:log:list', icon='file-text', visible='0', status='0'),
    # 基金信息管理页(管理 fund_info 缓存表的同步/新增/删除,2026-10-12)
    SysMenu(menu_id=105, menu_name='基金信息管理', parent_id=2, order_num=5, menu_type='C', path='/app/asset/fund-info-management', component='asset/fund-info-management', perms='fund:info:list', icon='database', visible='0', status='0'),
    SysMenu(menu_id=1051, menu_name='基金信息同步', parent_id=105, order_num=1, menu_type='F', perms='fund:info:sync', visible='0', status='0'),
    SysMenu(menu_id=1052, menu_name='基金信息新增', parent_id=105, order_num=2, menu_type='F', perms='fund:info:add', visible='0', status='0'),
    SysMenu(menu_id=1053, menu_name='基金信息删除', parent_id=105, order_num=3, menu_type='F', perms='fund:info:remove', visible='0', status='0'),
    # ===== 资产管理业务菜单(menu_id 分段:2=目录 200+=菜单 2000+=按钮) =====
    SysMenu(menu_id=2, menu_name='资产管理', parent_id=0, order_num=2, menu_type='M', path='/app/asset', icon='briefcase', visible='0', status='0'),
    # 基金管理页 + 操作按钮
    SysMenu(menu_id=200, menu_name='基金管理', parent_id=2, order_num=1, menu_type='C', path='/app/asset/funds', component='asset/funds', perms='fund:fund:list', icon='coins', visible='0', status='0'),
    SysMenu(menu_id=2001, menu_name='基金查询', parent_id=200, order_num=1, menu_type='F', perms='fund:fund:query', visible='0', status='0'),
    SysMenu(menu_id=2002, menu_name='基金新增', parent_id=200, order_num=2, menu_type='F', perms='fund:fund:add', visible='0', status='0'),
    SysMenu(menu_id=2003, menu_name='基金修改', parent_id=200, order_num=3, menu_type='F', perms='fund:fund:edit', visible='0', status='0'),
    SysMenu(menu_id=2004, menu_name='基金删除', parent_id=200, order_num=4, menu_type='F', perms='fund:fund:remove', visible='0', status='0'),
    SysMenu(menu_id=2005, menu_name='基金同步', parent_id=200, order_num=5, menu_type='F', perms='fund:fund:sync', visible='0', status='0'),
    SysMenu(menu_id=2006, menu_name='图表查询', parent_id=200, order_num=6, menu_type='F', perms='fund:chart:list', visible='0', status='0'),
    # 基金净值页 + 操作按钮(按需同步:看哪只同步哪只,不做全量跑表)
    # menu_id 204/2041/2042:202(资产配置)/203(指数管理)已为存量库手工菜单占用,勿复用
    SysMenu(menu_id=204, menu_name='基金净值', parent_id=2, order_num=2, menu_type='C', path='/app/asset/fund-navs', component='asset/fund-navs', perms='fund:nav:list', icon='chart-line', visible='0', status='0'),
    SysMenu(menu_id=2041, menu_name='净值查询', parent_id=204, order_num=1, menu_type='F', perms='fund:nav:list', visible='0', status='0'),
    SysMenu(menu_id=2042, menu_name='净值同步', parent_id=204, order_num=2, menu_type='F', perms='fund:nav:sync', visible='0', status='0'),
    # 持仓域不设菜单/按钮权限记录:持仓是行级隔离的私域数据,接口仅登录、
    # 入口在资产 tab 前端静态菜单(全员可见),原 201/2101~2111 记录由
    # scripts/migrate_portfolio_menu_cleanup.py 从存量库清理
    # 资产配置页 + 操作按钮
    SysMenu(menu_id=202, menu_name='资产配置', parent_id=2, order_num=3, menu_type='C', path='/app/asset/allocation', component='asset/allocation', perms='asset:class:list', icon='pie-chart', visible='0', status='0'),
    SysMenu(menu_id=2201, menu_name='类别新增', parent_id=202, order_num=1, menu_type='F', perms='asset:class:add', visible='0', status='0'),
    SysMenu(menu_id=2202, menu_name='类别修改', parent_id=202, order_num=2, menu_type='F', perms='asset:class:edit', visible='0', status='0'),
    SysMenu(menu_id=2203, menu_name='类别删除', parent_id=202, order_num=3, menu_type='F', perms='asset:class:remove', visible='0', status='0'),
    SysMenu(menu_id=2204, menu_name='模式查询', parent_id=202, order_num=4, menu_type='F', perms='asset:mode:query', visible='0', status='0'),
    SysMenu(menu_id=2205, menu_name='模式新增', parent_id=202, order_num=5, menu_type='F', perms='asset:mode:add', visible='0', status='0'),
    SysMenu(menu_id=2206, menu_name='模式修改', parent_id=202, order_num=6, menu_type='F', perms='asset:mode:edit', visible='0', status='0'),
    SysMenu(menu_id=2207, menu_name='模式删除', parent_id=202, order_num=7, menu_type='F', perms='asset:mode:remove', visible='0', status='0'),
    SysMenu(menu_id=2208, menu_name='映射新增', parent_id=202, order_num=8, menu_type='F', perms='asset:mapping:add', visible='0', status='0'),
    SysMenu(menu_id=2209, menu_name='映射删除', parent_id=202, order_num=9, menu_type='F', perms='asset:mapping:remove', visible='0', status='0'),
    SysMenu(menu_id=2210, menu_name='配置对比', parent_id=202, order_num=10, menu_type='F', perms='asset:allocation:compare', visible='0', status='0'),
    # 指数管理页(公共行情数据,不挂接口权限 → 无按钮记录;路径与前端 /app/asset/index-yields 路由逐字一致)
    SysMenu(menu_id=203, menu_name='指数管理', parent_id=2, order_num=4, menu_type='C', path='/app/asset/index-yields', component='asset/index-yields', perms='', icon='database', visible='0', status='0'),
]

# 种子字典(逐字镜像 src/testing/mocks/handlers/dicts.ts 的 dictStore)
SEED_DICT_TYPES = [
    SysDictType(dict_id=1, dict_name='用户性别', dict_type='sys_user_sex', status='0', create_by='system'),
    SysDictType(dict_id=2, dict_name='系统开关', dict_type='sys_normal_disable', status='0', create_by='system'),
    SysDictType(dict_id=3, dict_name='通知类型', dict_type='sys_notice_type', status='0', create_by='system'),
    # 4 个标准若依字典类型(渐进补种见 init 5.5 步)
    # 主键 ID 用高位段(8+/100+):避开用户自建数据的自增区间;幂等判重不靠主键,
    # 靠业务键 dict_type / (dict_type, dict_value)——已存在同类型不同 ID 也能正确跳过
    SysDictType(dict_id=8, dict_name='菜单显示状态', dict_type='sys_show_hide', status='0', create_by='system'),
    SysDictType(dict_id=9, dict_name='菜单类型', dict_type='sys_menu_type', status='0', create_by='system'),
    SysDictType(dict_id=10, dict_name='操作状态', dict_type='sys_oper_status', status='0', create_by='system'),
    SysDictType(dict_id=11, dict_name='操作类型', dict_type='sys_oper_type', status='0', create_by='system'),
    SysDictType(dict_id=12, dict_name='指数同步状态', dict_type='sys_index_sync_status', status='0', create_by='system'),
    SysDictType(dict_id=13, dict_name='持仓状态', dict_type='sys_position_status', status='0', create_by='system'),
]

SEED_DICT_DATA = [
    # sys_user_sex:男/女/未知
    SysDictData(dict_code=1, dict_sort=1, dict_label='男', dict_value='0', dict_type='sys_user_sex', css_class='tag-primary', status='0', create_by='system'),
    SysDictData(dict_code=2, dict_sort=2, dict_label='女', dict_value='1', dict_type='sys_user_sex', css_class='tag-danger', status='0', create_by='system'),
    SysDictData(dict_code=3, dict_sort=3, dict_label='未知', dict_value='2', dict_type='sys_user_sex', css_class='tag-info', status='0', create_by='system'),
    # sys_normal_disable:正常/停用
    SysDictData(dict_code=4, dict_sort=1, dict_label='正常', dict_value='0', dict_type='sys_normal_disable', css_class='tag-success', status='0', create_by='system'),
    SysDictData(dict_code=5, dict_sort=2, dict_label='停用', dict_value='1', dict_type='sys_normal_disable', css_class='tag-warning', status='0', create_by='system'),
    # sys_notice_type:通知/公告(无 cssClass)
    SysDictData(dict_code=6, dict_sort=1, dict_label='通知', dict_value='1', dict_type='sys_notice_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=7, dict_sort=2, dict_label='公告', dict_value='2', dict_type='sys_notice_type', css_class=None, status='0', create_by='system'),
    # ===== 系统管理页面字典 =====
    # css_class 统一不配:label 走字典、视觉归前端(彩色 Badge/图标由组件层管理——模式 B 职责切分)
    # sys_show_hide:显示/隐藏
    SysDictData(dict_code=100, dict_sort=1, dict_label='显示', dict_value='0', dict_type='sys_show_hide', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=101, dict_sort=2, dict_label='隐藏', dict_value='1', dict_type='sys_show_hide', css_class=None, status='0', create_by='system'),
    # sys_menu_type:目录/菜单/按钮
    SysDictData(dict_code=102, dict_sort=1, dict_label='目录', dict_value='M', dict_type='sys_menu_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=103, dict_sort=2, dict_label='菜单', dict_value='C', dict_type='sys_menu_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=104, dict_sort=3, dict_label='按钮', dict_value='F', dict_type='sys_menu_type', css_class=None, status='0', create_by='system'),
    # sys_oper_status:成功/失败
    SysDictData(dict_code=105, dict_sort=1, dict_label='成功', dict_value='0', dict_type='sys_oper_status', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=106, dict_sort=2, dict_label='失败', dict_value='1', dict_type='sys_oper_status', css_class=None, status='0', create_by='system'),
    # sys_oper_type:若依 10 项全量(对应后端 BusinessType 枚举)
    SysDictData(dict_code=107, dict_sort=0, dict_label='其它', dict_value='0', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=108, dict_sort=1, dict_label='新增', dict_value='1', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=109, dict_sort=2, dict_label='修改', dict_value='2', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=110, dict_sort=3, dict_label='删除', dict_value='3', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=111, dict_sort=4, dict_label='授权', dict_value='4', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=112, dict_sort=5, dict_label='导出', dict_value='5', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=113, dict_sort=6, dict_label='导入', dict_value='6', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=114, dict_sort=7, dict_label='强退', dict_value='7', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=115, dict_sort=8, dict_label='生成代码', dict_value='8', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=116, dict_sort=9, dict_label='清空数据', dict_value='9', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=117, dict_sort=10, dict_label='查询', dict_value='10', dict_type='sys_oper_type', css_class=None, status='0', create_by='system'),  # 项目扩展:查询类接口(值 10 非若依标准)
    # ===== 指数收益率管理页字典 =====
    SysDictData(dict_code=118, dict_sort=1, dict_label='已同步', dict_value='1', dict_type='sys_index_sync_status', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=119, dict_sort=2, dict_label='未同步', dict_value='0', dict_type='sys_index_sync_status', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=120, dict_sort=3, dict_label='已过期', dict_value='2', dict_type='sys_index_sync_status', css_class=None, status='0', create_by='system'),
    # ===== 持仓管理页字典(段位 13/150+:已核对存量库 max dict_id=12、max dict_code=120) =====
    # sys_position_status:正常/部分赎回/全部赎回(值与 position_do 的状态常量逐字一致)
    SysDictData(dict_code=150, dict_sort=1, dict_label='正常', dict_value='0', dict_type='sys_position_status', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=151, dict_sort=2, dict_label='部分赎回', dict_value='1', dict_type='sys_position_status', css_class=None, status='0', create_by='system'),
    SysDictData(dict_code=152, dict_sort=3, dict_label='全部赎回', dict_value='2', dict_type='sys_position_status', css_class=None, status='0', create_by='system'),
]

# admin 角色绑定的全部菜单
ADMIN_MENU_IDS = [1, 100, 1001, 1002, 1003, 1004,
                  101, 1101, 1102, 1103, 1104,
                  102, 1201, 1202, 1203, 1204,
                  103, 1301, 1302, 1303, 1304,
                  104,
                  105, 1051, 1052, 1053]


async def init_seed_data() -> None:
    """按表独立幂等插入种子:角色 → 菜单 → 用户(含角色绑定) → 角色菜单关联。"""
    async with AsyncSessionLocal() as db:
        # 1. 角色种子(sys_role 为空才插)
        role_count = (await db.execute(select(func.count()).select_from(SysRole))).scalar() or 0
        if role_count == 0:
            db.add_all([
                SysRole(role_id=1, role_name='超级管理员', role_key='admin', role_sort=1,
                        data_scope='1', menu_check_strictly=1, dept_check_strictly=1,
                        status='0', del_flag='0', create_by='system', create_time=datetime.now(),
                        remark='超级管理员(全权限)'),
                SysRole(role_id=2, role_name='普通角色', role_key='common', role_sort=2,
                        data_scope='5', menu_check_strictly=1, dept_check_strictly=1,
                        status='0', del_flag='0', create_by='system', create_time=datetime.now(),
                        remark='普通角色(最小权限演示)'),
            ])
            logger.info('🌱 种子角色已创建:admin(1) / common(2)')

        # 2. 菜单种子(sys_menu 为空才插;menu_id 手工指定,勿依赖自增)
        menu_count = (await db.execute(select(func.count()).select_from(SysMenu))).scalar() or 0
        if menu_count == 0:
            for menu in SEED_MENUS:
                menu.create_by = 'system'
                menu.create_time = datetime.now()
            db.add_all(SEED_MENUS)
            logger.info(f'🌱 种子菜单已创建:{len(SEED_MENUS)} 条')

        # 2.5 存量库渐进补种:按 menu_id 逐条幂等补插 + admin 角色补绑
        #     解决"表空才插"对存量库失效的问题(新加菜单种子后,老库不会出现新菜单)
        existing_menu_ids = set(
            row[0] for row in (await db.execute(select(SysMenu.menu_id))).all()
        )
        missing_menus = [m for m in SEED_MENUS if m.menu_id not in existing_menu_ids]
        if missing_menus:
            for menu in missing_menus:
                menu.create_by = 'system'
                menu.create_time = datetime.now()
            db.add_all(missing_menus)
            logger.info(f'🌱 存量库补种菜单 {len(missing_menus)} 条:menu_id={sorted(m.menu_id for m in missing_menus)}')

        # 2.6 结构漂移校正:menu_id 已存在但 parent_id/menu_type 与种子不符的行(如错插残留),
        #     重启时自动归位——补种只判存在性,不校这条的话种子改对也救不回库里的错行。
        #     只校决定树层级的两个结构字段;perms/order_num 等运行时可调字段不校,
        #     避免覆盖管理界面的人工修改。存量库手工菜单不在 SEED_MENUS,完全不涉及。
        #     注意必须 select 整个实体(ORM 实例)而非列元组,列元组的属性赋值不会持久化。
        existing_menus = (await db.execute(
            select(SysMenu).where(SysMenu.menu_id.in_([m.menu_id for m in SEED_MENUS]))
        )).scalars().all()
        existing_by_id = {menu_row.menu_id: menu_row for menu_row in existing_menus}
        for menu in SEED_MENUS:
            menu_row = existing_by_id.get(menu.menu_id)
            if menu_row is None:
                continue
            drifts = {}
            if menu_row.parent_id != menu.parent_id:
                drifts['parent_id'] = (menu_row.parent_id, menu.parent_id)
            if menu_row.menu_type != menu.menu_type:
                drifts['menu_type'] = (menu_row.menu_type, menu.menu_type)
            if drifts:
                menu_row.parent_id = menu.parent_id
                menu_row.menu_type = menu.menu_type
                detail = ', '.join(f'{k} {v[0]}→{v[1]}' for k, v in drifts.items())
                logger.info(f'🌱 菜单结构漂移已校正:menu_id={menu.menu_id} {detail}')
        # admin 角色补绑缺失的菜单(admin 走 role_key 通配,不依赖绑定,但保持数据一致性)
        existing_rm_ids = set(
            row[0]
            for row in (
                await db.execute(select(SysRoleMenu.menu_id).where(SysRoleMenu.role_id == 1))
            ).all()
        )
        missing_rm = [mid for mid in ADMIN_MENU_IDS if mid not in existing_rm_ids]
        if missing_rm:
            db.add_all([SysRoleMenu(role_id=1, menu_id=mid) for mid in missing_rm])
            logger.info(f'🌱 admin 角色补绑菜单 {len(missing_rm)} 条:menu_id={sorted(missing_rm)}')

        # 3. 用户种子(sys_user 为空才建,建完绑 admin 角色)
        user_count = (await db.execute(select(func.count()).select_from(SysUser))).scalar() or 0
        if user_count == 0:
            admin = SysUser(
                user_name='admin',
                nick_name='Admin',
                email=SEED_ADMIN_EMAIL,
                password=PwdUtil.get_password_hash(SEED_ADMIN_PASSWORD),
                status='0',
                del_flag='0',
                create_by='system',
                create_time=datetime.now(),
                remark='种子管理员账号',
            )
            db.add(admin)
            await db.flush()  # 回填自增 user_id(commit 前读取,规避 expire_on_commit)
            db.add(SysUserRole(user_id=admin.user_id, role_id=1))
            logger.info(f'🌱 种子管理员已创建:{SEED_ADMIN_EMAIL}(已绑 admin 角色,初始密码见配置)')
        else:
            # 存量环境补绑:用户已存在但关联表为空(如本次扩展前的老库)
            ur_count = (await db.execute(select(func.count()).select_from(SysUserRole))).scalar() or 0
            if ur_count == 0:
                db.add(SysUserRole(user_id=1, role_id=1))
                logger.info('🌱 存量管理员已补绑 admin 角色(user_id=1 ↔ role_id=1)')

        # 4. 角色菜单关联(sys_role_menu 为空才插;admin 全量,common 留空)
        rm_count = (await db.execute(select(func.count()).select_from(SysRoleMenu))).scalar() or 0
        if rm_count == 0:
            db.add_all([SysRoleMenu(role_id=1, menu_id=mid) for mid in ADMIN_MENU_IDS])
            logger.info(f'🌱 admin 角色已关联 {len(ADMIN_MENU_IDS)} 条菜单(common 角色留空)')

        # 5. 字典种子(sys_dict_type/sys_dict_data 各自判空才插)
        dict_type_count = (await db.execute(select(func.count()).select_from(SysDictType))).scalar() or 0
        if dict_type_count == 0:
            for t in SEED_DICT_TYPES:
                t.create_time = datetime.now()
            db.add_all(SEED_DICT_TYPES)
            logger.info('🌱 种子字典类型已创建:3 类(性别/开关/通知)')

        dict_data_count = (await db.execute(select(func.count()).select_from(SysDictData))).scalar() or 0
        if dict_data_count == 0:
            for d in SEED_DICT_DATA:
                d.create_time = datetime.now()
            db.add_all(SEED_DICT_DATA)
            logger.info('🌱 种子字典数据已创建:7 条')

        # 5.5 字典渐进补种:幂等补插(对齐菜单种子 missing_menus 模式)——
        #     解决"判空才插"对存量库失效:新增字典类型后老库自动补上。
        #     判重维度用业务键而非主键:类型按 dict_type(uk_dict_type 唯一约束)、
        #     数据按 (dict_type, dict_value)(uk_dict_value 同理)——主键 ID 会与用户自建数据
        #     冲突(实测踩坑:用户手工建的 dict_id=5 占了种子预定的 ID 段;主键判重还会漏
        #     "类型已存在但 ID 不同"的场景,触发 uk_dict_type 唯一约束回滚整个事务)
        existing_dict_types = set(
            row[0] for row in (await db.execute(select(SysDictType.dict_type))).all()
        )
        missing_dict_types = [t for t in SEED_DICT_TYPES if t.dict_type not in existing_dict_types]
        if missing_dict_types:
            for t in missing_dict_types:
                t.create_time = datetime.now()
            db.add_all(missing_dict_types)
            logger.info(f'🌱 存量库补种字典类型 {len(missing_dict_types)} 条:{sorted(t.dict_type for t in missing_dict_types)}')

        existing_dict_values = set(
            (row[0], row[1])
            for row in (await db.execute(select(SysDictData.dict_type, SysDictData.dict_value))).all()
        )
        missing_dict_data = [
            d for d in SEED_DICT_DATA
            if (d.dict_type, d.dict_value) not in existing_dict_values
        ]
        if missing_dict_data:
            for d in missing_dict_data:
                d.create_time = datetime.now()
            db.add_all(missing_dict_data)
            logger.info(f'🌱 存量库补种字典数据 {len(missing_dict_data)} 条:{sorted((d.dict_type, d.dict_value) for d in missing_dict_data)}')

        # 6. 自增序列同步:种子/补种手工指定主键的表,PG 序列不会自动前移——
        #    不同步则首个自增 INSERT 撞主键(菜单/角色管理页新增时必炸,实测抓出)。
        #    仅 PostgreSQL 需要(MySQL 的 AUTO_INCREMENT 插显式值后自动前移)。
        if DataBaseConfig.db_type == 'postgresql':
            for table, pk in (('sys_menu', 'menu_id'), ('sys_role', 'role_id'),
                              ('sys_dict_type', 'dict_id'), ('sys_dict_data', 'dict_code')):
                await db.execute(text(
                    f'SELECT setval(pg_get_serial_sequence(\'{table}\', \'{pk}\'), '
                    f'COALESCE((SELECT MAX({pk}) FROM {table}), 1))'
                ))
            logger.info('🌱 自增序列已同步(sys_menu/sys_role/sys_dict_type/sys_dict_data)')

        await db.commit()