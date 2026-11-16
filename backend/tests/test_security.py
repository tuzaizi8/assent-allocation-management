"""阶段八安全工具单元测试"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from config.settings import JwtConfig
from core.security import get_current_user
from utils.jwt_util import JwtUtil
from utils.pwd_util import PwdUtil

from core.context import RequestContext

from module_system.dao.menu_dao import MenuDao
from module_system.dao.user_dao import UserDao

from core.context_utils import get_current_user_or_none


class TestPwdUtil:
    """密码工具类测试"""

    def test_hash_returns_bcrypt_format(self):
        """哈希结果应为 bcrypt 格式 $2b$..."""
        hashed = PwdUtil.get_password_hash('123456')
        assert hashed.startswith('$2b$')
        # bcrypt 哈希固定 60 字符
        assert len(hashed) == 60

    def test_hash_includes_random_salt(self):
        """相同密码两次哈希结果应不同（盐随机）"""
        h1 = PwdUtil.get_password_hash('samepass')
        h2 = PwdUtil.get_password_hash('samepass')
        assert h1 != h2

    def test_verify_correct_password(self):
        """正确密码应校验通过"""
        hashed = PwdUtil.get_password_hash('mysecret')
        assert PwdUtil.verify_password('mysecret', hashed) is True

    def test_verify_wrong_password(self):
        """错误密码应校验失败"""
        hashed = PwdUtil.get_password_hash('correct')
        assert PwdUtil.verify_password('wrong', hashed) is False

    def test_verify_empty_hash(self):
        """空哈希应返回 False 而非抛异常"""
        assert PwdUtil.verify_password('anything', '') is False


class TestJwtUtil:
    """JWT 工具类测试"""

    def test_create_and_decode_roundtrip(self):
        """生成 → 解码 往返测试"""
        payload = {'user_id': 1, 'username': 'admin'}
        token = JwtUtil.create_access_token(payload)
        decoded = JwtUtil.decode_token(token)
        assert decoded['user_id'] == 1
        assert decoded['username'] == 'admin'
        assert 'exp' in decoded

    def test_token_with_bearer_prefix(self):
        """支持 Bearer 前缀"""
        token = JwtUtil.create_access_token({'user_id': 2})
        decoded = JwtUtil.decode_token(f'Bearer {token}')
        assert decoded['user_id'] == 2

    def test_custom_expires_delta(self):
        """自定义过期时长应被尊重"""
        token = JwtUtil.create_access_token(
            {'user_id': 3},
            expires_delta=timedelta(seconds=-1),  # 已过期
        )
        with pytest.raises(Exception):
            JwtUtil.decode_token(token)

    def test_invalid_token_raises(self):
        """非法 token 应抛异常"""
        with pytest.raises(Exception):
            JwtUtil.decode_token('not.a.valid.jwt')


class FakeSessionRedis:
    """只实现鉴权用到的 get:值可控,用来模拟"会话匹配 / 已被删或被覆盖 / Redis 不可用"。"""

    def __init__(self, value=None, boom: bool = False) -> None:
        self.value = value
        self.boom = boom

    async def get(self, key):
        if self.boom:
            raise RuntimeError('redis down')
        return self.value


def make_request(redis=None) -> Request:
    """最小 Request:鉴权依赖只从 scope['app'].state.redis 读会话值。"""
    app = SimpleNamespace(state=SimpleNamespace(redis=redis or FakeSessionRedis()))
    return Request(
        {
            'type': 'http',
            'method': 'GET',
            'path': '/x',
            'scheme': 'http',
            'server': ('localhost', 8000),
            'headers': [],
            'query_string': b'',
            'app': app,
        }
    )


def patch_user(monkeypatch, status: str = '0') -> None:
    """把查库/角色两处依赖换成桩:所有会话校验用例共用。"""

    async def fake_get_user_by_id(db, user_id):
        return SimpleNamespace(
            user_id=user_id, user_name='admin', nick_name='管理员', dept_id=None, status=status
        )

    async def fake_get_role_keys(db, user_id):
        return ['admin']

    monkeypatch.setattr(UserDao, 'get_user_by_id', fake_get_user_by_id)
    monkeypatch.setattr(MenuDao, 'get_user_role_keys', fake_get_role_keys)


class TestGetCurrentUser:
    """依赖注入函数测试"""

    @pytest.mark.asyncio
    async def test_valid_token_returns_payload(self,monkeypatch):
        """合法 token 返回 payload"""
        fake_user = SimpleNamespace(user_id=1, user_name="admin", nick_name="管理员", dept_id=None, status="0")
        async def fake_get_user_by_id(db, user_id):
            return fake_user
        async def fake_get_role_keys(db, user_id):
            return ["admin"]

        monkeypatch.setattr(UserDao, "get_user_by_id", fake_get_user_by_id)
        monkeypatch.setattr(MenuDao, "get_user_role_keys", fake_get_role_keys)

        token = JwtUtil.create_access_token({'user_id': 1, 'username': 'admin'})
        # 会话值与本请求 token 一致才算登录态有效(鉴权依赖新增的会话校验)
        payload = await get_current_user(
            request=make_request(FakeSessionRedis(token)), token=token, query_db=None
        )
        assert payload['user_id'] == 1
        # 查表装配断言:上下文里五字段齐活(而非 payload 拼的)
        current = get_current_user_or_none()
        assert current is not None
        assert current.user_name == "admin"  # 以库为准
        assert current.nick_name == "管理员"
        assert current.is_admin is True  # 角色含 admin
        RequestContext.clear_all()  # 清理,防泄漏到同进程后续用例

    @pytest.mark.asyncio
    async def test_invalid_token_raises_auth_exception(self):
        """非法 token 抛 AuthException（处理器映射 401）"""
        from exceptions.exceptions import AuthException
        with pytest.raises(AuthException):
            await get_current_user(request=make_request(), token='invalid.token.here', query_db=None)

    @pytest.mark.asyncio
    async def test_missing_user_id_raises(self):
        """payload 缺 user_id 抛 AuthException"""
        from exceptions.exceptions import AuthException
        # 手动构造一个无 user_id 的 token
        import jwt
        token = jwt.encode(
            {'username': 'hacker'},
            JwtConfig.jwt_secret_key,
            algorithm=JwtConfig.jwt_algorithm,
        )
        with pytest.raises(AuthException):
            await get_current_user(request=make_request(), token=token, query_db=None)

    @pytest.mark.asyncio
    async def test_deleted_user_raises(self, monkeypatch):
        """用户不存在/已删除(查库 None)→ AuthException(停用分流至下方显式检查用例)"""
        from exceptions.exceptions import AuthException

        async def fake_get_user_by_id(db, user_id):
            return None

        monkeypatch.setattr(UserDao, "get_user_by_id", fake_get_user_by_id)
        token = JwtUtil.create_access_token({"user_id": 99})
        with pytest.raises(AuthException):
            await get_current_user(request=make_request(), token=token, query_db=None)

    @pytest.mark.asyncio
    async def test_disabled_user_raises(self, monkeypatch):
        """停用用户(status='1')→ AuthException(get_user_by_id 不再过滤 status,由鉴权层显式拦截)"""
        from exceptions.exceptions import AuthException

        async def fake_get_user_by_id(db, user_id):
            return SimpleNamespace(user_id=99, user_name="foo", nick_name="停用户", dept_id=None, status="1")

        monkeypatch.setattr(UserDao, "get_user_by_id", fake_get_user_by_id)
        token = JwtUtil.create_access_token({"user_id": 99})
        with pytest.raises(AuthException):
            await get_current_user(request=make_request(), token=token, query_db=None)


class TestGetCurrentUserSession:
    """鉴权依赖的会话校验:登出/挤下线/改密后旧 token 必须立刻失效(不再等 JWT 过期)"""

    @pytest.mark.asyncio
    async def test_matching_session_passes(self, monkeypatch):
        patch_user(monkeypatch)
        token = JwtUtil.create_access_token({'user_id': 1})
        payload = await get_current_user(
            request=make_request(FakeSessionRedis(token)), token=token, query_db=None
        )
        assert payload['user_id'] == 1
        RequestContext.clear_all()

    @pytest.mark.asyncio
    async def test_stale_session_raises(self, monkeypatch):
        """Redis 里存的是新 token(被挤下线/改密后重登)→ 旧 token 立即 401"""
        from exceptions.exceptions import AuthException

        patch_user(monkeypatch)
        old_token = JwtUtil.create_access_token({'user_id': 1})
        with pytest.raises(AuthException):
            await get_current_user(
                request=make_request(FakeSessionRedis('a-newer-token')),
                token=old_token,
                query_db=None,
            )

    @pytest.mark.asyncio
    async def test_missing_session_raises(self, monkeypatch):
        """会话键不存在(登出被删 / Redis 被清)→ 401,与 /auth/me 同口径"""
        from exceptions.exceptions import AuthException

        patch_user(monkeypatch)
        token = JwtUtil.create_access_token({'user_id': 1})
        with pytest.raises(AuthException):
            await get_current_user(
                request=make_request(FakeSessionRedis(None)), token=token, query_db=None
            )

    @pytest.mark.asyncio
    async def test_redis_error_fails_open(self, monkeypatch):
        """Redis 不可用时 fail-open:JWT 仍是有效凭据,不能把可用性问题放大成全站 401"""
        patch_user(monkeypatch)
        token = JwtUtil.create_access_token({'user_id': 1})
        payload = await get_current_user(
            request=make_request(FakeSessionRedis(boom=True)), token=token, query_db=None
        )
        assert payload['user_id'] == 1
        RequestContext.clear_all()
