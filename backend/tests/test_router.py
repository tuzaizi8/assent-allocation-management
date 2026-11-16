"""路由自动注册机制的单元测试。

覆盖：
1. APIRouterPro 的 order_num / auto_register 默认值
2. RouterRegister 能扫描到示例 controller
3. 排序规则正确
4. 路由确实被注册到 FastAPI 应用
5. auto_register=False 的 router 不被注册
"""

from fastapi import APIRouter, FastAPI

from common.router import APIRouterPro, RouterRegister, auto_register_routers


def test_apirouterpro_defaults():
    """APIRouterPro 的默认参数应正确。"""
    router = APIRouterPro()
    assert router.order_num == 100
    assert router.auto_register is True


def test_apirouterpro_custom_params():
    """APIRouterPro 应接受自定义参数。"""
    router = APIRouterPro(prefix='/test', order_num=5, auto_register=False, tags=['test'])
    assert router.order_num == 5
    assert router.auto_register is False
    # 父类属性也应正确
    assert router.prefix == '/test'
    assert router.tags == ['test']


def test_router_register_sort():
    """排序规则：APIRouterPro 优先，order_num 升序，再按变量名。"""
    r1 = APIRouterPro(order_num=10)
    r2 = APIRouterPro(order_num=3)
    r3 = APIRouter()  # 普通 APIRouter

    register = RouterRegister.__new__(RouterRegister)
    sorted_routers = register._sort_routers([
        ('a', r1),
        ('b', r2),
        ('c', r3),
    ])

    # 期望顺序：b (order_num=3) -> a (order_num=10) -> c (普通 APIRouter)
    assert sorted_routers[0][0] == 'b'
    assert sorted_routers[1][0] == 'a'
    assert sorted_routers[2][0] == 'c'


def test_auto_register_routers_registers_controllers():
    """auto_register_routers 应扫描并注册各模块 controller 的路由。

    starlette 1.6+ 将 include_router 的路由惰性包进 _IncludedRouter,app.routes
    上无法直接读到 path,故用 url_path_for 校验路由确已注册。
    """
    app = FastAPI()
    auto_register_routers(app)

    # 抽查系统模块与业务模块各一条已注册路由(业务 controller 文件名不以 _ 开头才会被扫描)
    assert app.url_path_for('get_role_list') == '/system/role/list'
    assert app.url_path_for('get_fund_list') == '/fund/list'
    assert app.url_path_for('get_positions') == '/portfolio/position/list'
    assert app.url_path_for('get_asset_classes') == '/asset/class/list'


def test_auto_register_false_skipped():
    """auto_register=False 的 router 不应被注册。"""
    app = FastAPI()
    auto_register_routers(app)

    # 定义一个 auto_register=False 的 router
    skipped = APIRouterPro(prefix='/skipped', auto_register=False)

    @skipped.get('/x')
    async def x():
        return {'ok': True}

    # 再次触发注册（模拟在另一个模块中定义）
    register = RouterRegister(app)
    routers = register._import_module_and_get_routers(register._find_controller_files())

    # 不应包含 auto_register=False 的实例
    for _name, router in routers:
        if isinstance(router, APIRouterPro):
            assert router.auto_register is True