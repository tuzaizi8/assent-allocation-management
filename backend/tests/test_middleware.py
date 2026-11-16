"""
中间件链集成测试
验证 CORS / Gzip / Trace 响应头 / 上下文清理 四类中间件协同工作
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middlewares.handle import handle_middleware
from middlewares.trace_middleware import TraceCtx


def _build_app() -> FastAPI:
    """构建带完整中间件链的测试 app"""
    app = FastAPI()

    # 注册中间件链
    handle_middleware(app)

    @app.get('/hello')
    async def hello():
        # 在路由内读取 trace 上下文，验证 ContextVar 已注入
        return {
            'trace_id': TraceCtx.get_trace_id(),
            'request_id': TraceCtx.get_request_id(),
            'span_id': TraceCtx.get_span_id(),
            'path': TraceCtx.get_request_path(),
            'method': TraceCtx.get_request_method(),
        }

    @app.get('/big')
    async def big_response():
        # 返回 > 1000 字节的响应，触发 gzip 压缩
        return {'data': 'x' * 2000}

    return app


def test_trace_response_headers():
    """验证 Trace 中间件注入了 trace-id / request-id / span-id 响应头"""
    app = _build_app()
    client = TestClient(app)

    response = client.get('/hello')

    assert response.status_code == 200
    # 三个 trace 头必须存在且为 32 位 hex
    assert 'trace-id' in response.headers
    assert 'request-id' in response.headers
    assert 'span-id' in response.headers
    assert len(response.headers['trace-id']) == 32
    assert len(response.headers['request-id']) == 32
    assert len(response.headers['span-id']) == 32


def test_trace_context_in_route():
    """验证路由内能通过 ContextVar 读到 trace 上下文"""
    app = _build_app()
    client = TestClient(app)

    response = client.get('/hello')
    body = response.json()

    # 路由内读到的 trace_id 应与响应头一致
    assert body['trace_id'] == response.headers['trace-id']
    assert body['request_id'] == response.headers['request-id']
    assert body['span_id'] == response.headers['span-id']
    assert body['path'] == '/hello'
    assert body['method'] == 'GET'


def test_gzip_compression():
    """验证 Gzip 中间件对大响应做了压缩"""
    app = _build_app()
    # TestClient 默认带 Accept-Encoding: gzip
    client = TestClient(app)

    response = client.get('/big')

    assert response.status_code == 200
    assert response.headers.get('content-encoding') == 'gzip'
    # TestClient 会自动解压，json() 仍可正常解析
    assert len(response.json()['data']) == 2000


def test_gzip_skip_small_response():
    """验证小响应不压缩"""
    app = _build_app()
    client = TestClient(app)

    response = client.get('/hello')

    # /hello 响应体 < 1000 字节，不应压缩
    assert response.headers.get('content-encoding') != 'gzip'


def test_cors_preflight():
    """验证 CORS 预检请求返回正确头"""
    app = _build_app()
    client = TestClient(app)

    response = client.options(
        '/hello',
        headers={
            'Origin': 'http://localhost:3000',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'content-type',
        },
    )

    assert response.status_code == 200
    assert 'access-control-allow-origin' in response.headers
    assert 'access-control-allow-methods' in response.headers


def test_cors_actual_request():
    """验证实际跨域请求带 CORS 响应头"""
    app = _build_app()
    client = TestClient(app)

    response = client.get('/hello', headers={'Origin': 'http://localhost:3000'})

    assert response.status_code == 200
    assert 'access-control-allow-origin' in response.headers


def test_context_cleanup_after_request():
    """
    验证上下文清理中间件在请求结束后清空了 ContextVar
    请求结束后再读取应得到默认空串
    """
    app = _build_app()
    client = TestClient(app)

    client.get('/hello')

    # 请求结束后，trace 上下文应被清理为空串
    assert TraceCtx.get_trace_id() == ''
    assert TraceCtx.get_request_id() == ''
    assert TraceCtx.get_span_id() == ''


def test_trace_id_different_per_request():
    """验证每次请求生成不同的 trace_id"""
    app = _build_app()
    client = TestClient(app)

    r1 = client.get('/hello')
    r2 = client.get('/hello')

    assert r1.headers['trace-id'] != r2.headers['trace-id']
    assert r1.headers['request-id'] != r2.headers['request-id']