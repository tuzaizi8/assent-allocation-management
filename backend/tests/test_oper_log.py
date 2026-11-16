"""日志管理模块单元测试(2026-08-27 P3-5:操作日志 + 登录日志)。

覆盖三块:
① VO 驼峰别名解析(camelCase 查询参数 → snake_case 字段,单页双 Tab 契约锚点)
② 登录日志 operName 回填(login_services 成功路径设置 request.state)
③ @Log wrapper 覆写(落库前读取 request.state.log_oper_name 覆写 oper_name)
对齐 test_user_service.py 的 monkeypatch 风格。
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from module_system.entity.vo.oper_log_vo import OperLogQueryModel
from module_system.service.auth_service import AuthService
from module_system.entity.vo.auth_vo import LoginModel


class TestOperLogQueryModel:
    """查询模型驼峰别名解析"""

    def test_camel_alias_resolution(self):
        """前端 camelCase 查询参数应映射到 snake_case 字段"""
        model = OperLogQueryModel.model_validate(
            {
                'category': 'login',
                'title': '认证管理',
                'operName': 'admin',
                'status': 1,
                'beginTime': '2026-08-01',
                'endTime': '2026-08-27',
                'pageNum': 2,
                'pageSize': 20,
            }
        )
        assert model.category == 'login'
        assert model.title == '认证管理'
        assert model.oper_name == 'admin'
        assert model.status == 1
        assert model.begin_time == '2026-08-01'
        assert model.end_time == '2026-08-27'
        assert model.page_num == 2
        assert model.page_size == 20

    def test_category_defaults_to_operation(self):
        """category 缺省为 operation(操作日志 Tab 默认)"""
        model = OperLogQueryModel()
        assert model.category == 'operation'
        assert model.page_num == 1
        assert model.page_size == 10


def make_request() -> Request:
    """构造最小可用 starlette Request(@Log 的 _extract_request 用 isinstance 校验,
    SimpleNamespace 过不了;state 是 starlette 原生属性,直接赋值)"""
    scope = {
        'type': 'http',
        'method': 'POST',
        'path': '/auth/login',
        'scheme': 'http',
        'server': ('localhost', 8000),
        'headers': [],
        'query_string': b'',
        'path_params': {},
    }
    return Request(scope)


class TestLoginOperNameBackfill:
    """登录日志 operName 回填(request.state 传递)"""

    @pytest.mark.asyncio
    async def test_login_success_sets_state(self, monkeypatch):
        """登录成功 → request.state.log_oper_name 已设置(供 @Log wrapper 覆写)"""
        fake_user = SimpleNamespace(
            user_id=1, user_name='admin', email='admin@assent.local', nick_name='Admin',
            status='0', login_ip=None, login_date=None, password='hashed',
        )

        async def fake_get_user_by_email(db, email):
            return fake_user

        monkeypatch.setattr('module_system.dao.user_dao.UserDao.get_user_by_email', fake_get_user_by_email)
        monkeypatch.setattr('utils.pwd_util.PwdUtil.verify_password', lambda p, h: True)

        class FakeRedis:
            async def set(self, *a, **kw):
                return None

        class FakeDb:
            async def commit(self):
                return None

        async def fake_build_auth_user(db, user):
            return SimpleNamespace(model_dump=lambda **kw: {'id': '1'})

        monkeypatch.setattr(AuthService, 'build_auth_user', fake_build_auth_user)

        request = make_request()
        login_model = LoginModel(email='admin@assent.local', password='password123')

        await AuthService.login_services(FakeDb(), FakeRedis(), login_model, request)

        assert request.state.log_oper_name == 'admin'


class TestLogWrapperOverride:
    """@Log wrapper 的 oper_name 覆写(落库前读 request.state)"""

    @pytest.mark.asyncio
    async def test_wrapper_overrides_oper_name(self, monkeypatch):
        """被装饰方法内设置 request.state.log_oper_name → 入队 dict 的 oper_name 被覆写"""
        captured: dict = {}

        def fake_enqueue(oper_log: dict) -> None:
            captured.update(oper_log)

        # patch 模块内引用名(模块级 from import,须 patch 消费模块的绑定)
        monkeypatch.setattr('common.annotation.log_annotation.enqueue_oper_log', fake_enqueue)

        from common.annotation.log_annotation import BusinessType, Log, LogMode

        @Log(title='测试模块', business_type=BusinessType.OTHER, mode=LogMode.AROUND)
        async def endpoint(request):
            # 业务逻辑(登录场景)成功后回填——oper_name 构造时是 anonymous
            request.state.log_oper_name = 'admin'
            return SimpleNamespace(body=b'{"code":200}')

        await endpoint(make_request())

        assert captured['oper_name'] == 'admin'
        assert captured['title'] == '测试模块'
        assert captured['category'] == 'operation'  # 缺省类别

    @pytest.mark.asyncio
    async def test_wrapper_keeps_anonymous_without_state(self, monkeypatch):
        """未设置 request.state.log_oper_name(如登录失败) → oper_name 保持 anonymous"""
        captured: dict = {}

        def fake_enqueue(oper_log: dict) -> None:
            captured.update(oper_log)

        monkeypatch.setattr('common.annotation.log_annotation.enqueue_oper_log', fake_enqueue)

        from common.annotation.log_annotation import BusinessType, Log, LogMode

        @Log(title='测试模块', business_type=BusinessType.OTHER, mode=LogMode.AROUND, category='login')
        async def endpoint(request):
            # 失败路径:业务抛异常,不设置 state
            raise ValueError('用户名或密码错误')

        with pytest.raises(ValueError):
            await endpoint(make_request())

        # @Log 捕获异常重抛,但 finally 仍落日志:oper_name 保持 anonymous(语义正确)
        assert captured['oper_name'] == 'anonymous'
        assert captured['status'] == 1
        assert captured['error_msg'] == '用户名或密码错误'
        assert captured['category'] == 'login'


class TestLogResultMasking:
    """json_result 敏感键脱敏(安全修复:登录响应含有效 JWT,日志页可全量回读)"""

    @pytest.mark.asyncio
    async def test_jwt_and_password_masked_before_enqueue(self, monkeypatch):
        """登录响应体含 jwt 与密码哈希 → 入队 json_result 全部置 '***'"""
        captured: dict = {}
        monkeypatch.setattr(
            'common.annotation.log_annotation.enqueue_oper_log', lambda d: captured.update(d)
        )

        from common.annotation.log_annotation import BusinessType, Log, LogMode

        body = (
            b'{"code":200,"data":{"jwt":"eyJhbGciOiJIUzI1NiJ9.secret-payload",'
            b'"user":{"id":"1","password":"$2b$12$hash-value"}}}'
        )

        @Log(title='测试模块', business_type=BusinessType.OTHER, mode=LogMode.AROUND)
        async def endpoint(request):
            return SimpleNamespace(body=body)

        await endpoint(make_request())

        json_result = captured['json_result']
        assert 'eyJhbGciOiJIUzI1NiJ9' not in json_result
        assert '$2b$12$hash-value' not in json_result
        assert json_result.count('"***"') >= 2

    def test_mask_json_text_fallback_on_non_json(self):
        """非法 JSON → 正则回退仍能脱敏字符串级键值"""
        from utils.mask_util import mask_json_text

        out = mask_json_text('prefix garbage "token": "abc123" tail')
        assert '"token": "***"' in out
        assert 'abc123' not in out

    def test_mask_before_truncate(self):
        """先脱敏后截断:敏感值在 2KB 截断线之前也必须被置 '***'"""
        from common.annotation.log_annotation import Log

        log = Log(title='截断测试')
        jwt = 'eyJhbGciOiJIUzI1NiJ9.truncated-target'
        filler = 'x' * 3000
        result = log._serialize_result(
            SimpleNamespace(body=f'{{"jwt":"{jwt}","data":"{filler}"}}'.encode('utf-8'))
        )
        assert 'truncated-target' not in result
        assert '"***"' in result
        assert '...[截断' in result


def test_all_log_endpoints_declare_request():
    """@Log 用 isinstance 从实参里找 Request:漏写 request 形参会直接 500(模板下载首版即踩)。

    静态扫源码(不导入应用,不依赖 DB/Redis/鉴权),把整类错误在 CI 拦下。
    """
    repo_root = Path(__file__).resolve().parent.parent
    missing: list[str] = []
    for path in sorted(repo_root.glob('module_*/controller/*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [ast.unparse(item) for item in node.decorator_list]
            methods = {'get', 'post', 'put', 'delete', 'patch', 'head', 'options'}
            is_route = any(
                d.split('(')[0].rsplit('.', 1)[-1] in methods for d in decorators
            )
            if not (is_route and any(d.startswith('Log(') for d in decorators)):
                continue
            params = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            has_request = any(
                p.annotation is not None and 'Request' in ast.unparse(p.annotation)
                for p in params
            )
            if not has_request:
                missing.append(f'{path.name}:{node.lineno} {node.name}')
    assert missing == [], (
        f'这些 @Log 端点缺 Request 形参(补一个 request: Request,或去掉 @Log): {missing}'
    )
