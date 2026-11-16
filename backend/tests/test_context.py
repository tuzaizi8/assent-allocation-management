"""
请求上下文测试

验证：
1. RequestContext 的 set/get/reset/clear_all 基础功能
2. Token reset 能精确回滚到旧值
3. 多请求之间的 ContextVar 隔离（关键！）
4. ContextCleanupMiddleware 在请求结束后清理上下文
5. context_utils 便捷函数工作正常
"""
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from core.context import CurrentUser, RequestContext
from exceptions.exceptions import LoginException
from core.context_utils import (
    get_current_user,
    get_current_user_or_none,
    get_trace_id,
    set_current_user,
)
from middlewares.handle import handle_middleware
from middlewares.trace_middleware import TraceCtx


# --------------------------------------------------------------------------- #
# 测试夹具
# --------------------------------------------------------------------------- #
def _make_user(user_id: int, name: str = 'alice') -> CurrentUser:
    """构造测试用户"""
    return CurrentUser(
        user_id=user_id,
        user_name=name,
        nick_name=name.capitalize(),
        dept_id=100,
        is_admin=False,
    )


def _build_app() -> FastAPI:
    """构建带完整中间件链 + 上下文测试路由的 app"""
    app = FastAPI()

    # 注册完整中间件链（含 Trace + ContextCleanup）
    handle_middleware(app)

    async def _set_user_dep():
        """模拟鉴权依赖：写入 current_user"""
        user = _make_user(1, 'alice')
        set_current_user(user)
        return user

    @app.get('/whoami')
    async def whoami(user: CurrentUser = Depends(_set_user_dep)):
        # 路由内通过 context_utils 读取上下文
        return {
            'user_id': get_current_user().user_id,
            'user_name': get_current_user().user_name,
            'trace_id': get_trace_id(),
        }

    @app.get('/public')
    async def public():
        # 公开接口不写 current_user，应返回 None
        return {
            'user': get_current_user_or_none() is None,
            'trace_id': get_trace_id(),
        }

    return app


# --------------------------------------------------------------------------- #
# 1. 基础功能测试
# --------------------------------------------------------------------------- #
def test_set_and_get_current_user():
    """验证 set/get 配对工作"""
    token = RequestContext.set_current_user(_make_user(1, 'alice'))
    user = RequestContext.get_current_user()
    assert user.user_id == 1
    assert user.user_name == 'alice'
    # 清理
    RequestContext.reset_current_user(token)


def test_get_current_user_raises_when_none():
    """验证未设置时 get_current_user 抛 LoginException"""
    # 确保当前 Context 里没有 user
    RequestContext.clear_all()
    with pytest.raises(LoginException, match='当前用户信息为空'):
        RequestContext.get_current_user()


def test_get_current_user_or_none_returns_none():
    """验证未设置时 get_current_user_or_none 返回 None"""
    RequestContext.clear_all()
    assert get_current_user_or_none() is None


# --------------------------------------------------------------------------- #
# 2. Token reset 测试
# --------------------------------------------------------------------------- #
def test_token_reset_rolls_back_to_old_value():
    """验证 Token reset 能回滚到 set 之前的值"""
    # 先写入 alice
    token_alice = RequestContext.set_current_user(_make_user(1, 'alice'))
    assert RequestContext.get_current_user().user_name == 'alice'

    # 再写入 bob，拿到新 token
    token_bob = RequestContext.set_current_user(_make_user(2, 'bob'))
    assert RequestContext.get_current_user().user_name == 'bob'

    # reset bob → 应回滚到 alice
    RequestContext.reset_current_user(token_bob)
    assert RequestContext.get_current_user().user_name == 'alice'

    # reset alice → 应回滚到 None（默认值）
    RequestContext.reset_current_user(token_alice)
    assert get_current_user_or_none() is None


def test_token_reset_only_once():
    """验证 Token 只能 reset 一次（重复 reset 抛 contextvars 内置 RuntimeError）"""
    token = RequestContext.set_current_user(_make_user(1, 'alice'))
    RequestContext.reset_current_user(token)
    with pytest.raises(RuntimeError):
        # 重复 reset 由 contextvars 标准库抛 RuntimeError（与 LoginException 无关）
        RequestContext.reset_current_user(token)


# --------------------------------------------------------------------------- #
# 3. clear_all 测试
# --------------------------------------------------------------------------- #
def test_clear_all_resets_all_vars():
    """验证 clear_all 把所有业务上下文重置为 None"""
    RequestContext.set_current_user(_make_user(1, 'alice'))
    RequestContext.set_current_exclude_patterns([{'path': '/public'}])

    RequestContext.clear_all()

    assert get_current_user_or_none() is None
    assert RequestContext.get_current_exclude_patterns() == []


# --------------------------------------------------------------------------- #
# 4. 请求间隔离测试（核心！）
# --------------------------------------------------------------------------- #
def test_context_isolation_between_requests():
    """验证两个请求的 current_user 互不串扰"""
    app = _build_app()
    client = TestClient(app)

    # 请求 1：会写入 alice
    r1 = client.get('/whoami')
    assert r1.status_code == 200
    assert r1.json()['user_name'] == 'alice'
    trace_id_1 = r1.json()['trace_id']

    # 请求 2：同样是 alice，但 trace_id 应不同
    r2 = client.get('/whoami')
    assert r2.status_code == 200
    assert r2.json()['user_name'] == 'alice'
    trace_id_2 = r2.json()['trace_id']

    # 关键断言：两次请求的 trace_id 必须不同（证明 ContextVar 隔离）
    assert trace_id_1 != trace_id_2
    assert trace_id_1 != ''
    assert trace_id_2 != ''


def test_context_cleanup_after_request():
    """验证请求结束后 ContextVar 被清理"""
    app = _build_app()
    client = TestClient(app)

    client.get('/whoami')

    # 请求结束后，业务上下文应被清理
    assert get_current_user_or_none() is None
    # 追踪上下文也应被清理（重置为空串）
    assert TraceCtx.get_trace_id() == ''


def test_public_route_does_not_see_user():
    """验证公开接口读不到其他请求写入的用户"""
    app = _build_app()
    client = TestClient(app)

    # 先请求需要登录的接口
    client.get('/whoami')
    # 再请求公开接口，应读不到 user
    r = client.get('/public')
    assert r.status_code == 200
    assert r.json()['user'] is True  # user is None → True


def test_concurrent_requests_isolation():
    """验证并发请求的上下文隔离（用线程池模拟并发）"""
    import concurrent.futures

    app = _build_app()
    client = TestClient(app)

    def _hit(_i: int):
        r = client.get('/whoami')
        return r.json()['user_id']

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_hit, range(8)))

    # 8 次请求都应成功且拿到 user_id=1（不串号、不报错）
    assert results == [1] * 8


# --------------------------------------------------------------------------- #
# 5. context_utils 集成测试
# --------------------------------------------------------------------------- #
def test_context_utils_in_route():
    """验证 context_utils 在路由内可正常读取上下文"""
    app = _build_app()
    client = TestClient(app)

    r = client.get('/whoami')
    body = r.json()

    # 路由内通过 get_current_user / get_trace_id 读取
    assert body['user_id'] == 1
    assert body['user_name'] == 'alice'
    # trace_id 应与响应头一致
    assert body['trace_id'] == r.headers['trace-id']