"""
四个中间件效果演示测试

运行方式（必须加 -s 才能看到 print 输出）：
    pytest tests/test_middleware_demo.py -v -s

展示内容：
    1. Trace 中间件：trace_id / request_id / span_id 的实际长相（32 位 hex）
                    响应头里的 trace 三件套
    2. CORS 中间件：预检请求（OPTIONS）的响应头
                   实际跨域请求的响应头
    3. Gzip 中间件：大响应被压缩（content-encoding: gzip，大小对比）
                   小响应不压缩
    4. ContextCleanup 中间件：请求前 ContextVar 为空
                              请求中 ContextVar 有值
                              请求后 ContextVar 被清理（变回空串）
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middlewares.handle import handle_middleware
from middlewares.trace_middleware import TraceCtx


def _build_app() -> FastAPI:
    """构建带完整中间件链的测试 app"""
    app = FastAPI()
    handle_middleware(app)

    @app.get('/hello')
    async def hello():
        # 路由内能读到 ContextVar 注入的 trace 上下文
        return {
            'trace_id': TraceCtx.get_trace_id(),
            'request_id': TraceCtx.get_request_id(),
            'span_id': TraceCtx.get_span_id(),
            'path': TraceCtx.get_request_path(),
            'method': TraceCtx.get_request_method(),
            'msg': 'hello world',
        }

    @app.get('/big')
    async def big_response():
        # 返回 > 1000 字节，触发 gzip 压缩
        return {'data': 'x' * 2000}

    return app


def _print_headers(title: str, headers) -> None:
    """美化打印响应头"""
    print(f'\n  【{title}】')
    for key, value in headers.items():
        print(f'    {key}: {value}')


# ============================================================
# 1. Trace 中间件
# ============================================================
def test_trace_middleware_demo():
    """展示 Trace 中间件：trace_id 长什么样、响应头里有什么"""
    print('\n' + '=' * 70)
    print('中间件 1/4：Trace 中间件（链路追踪）')
    print('=' * 70)

    app = _build_app()
    client = TestClient(app)

    print('\n→ 发送 GET /hello 请求')
    response = client.get('/hello')

    print('\n  【响应状态码】')
    print(f'    {response.status_code}')

    _print_headers('响应头（完整）', response.headers)

    print('\n  【Trace 三件套的实际长相】')
    print(f'    trace-id   = {response.headers.get("trace-id")!r}'
          f'  (长度 {len(response.headers.get("trace-id", ""))})')
    print(f'    request-id = {response.headers.get("request-id")!r}'
          f'  (长度 {len(response.headers.get("request-id", ""))})')
    print(f'    span-id    = {response.headers.get("span-id")!r}'
          f'  (长度 {len(response.headers.get("span-id", ""))})')

    print('\n  【路由内通过 ContextVar 读到的值（应与响应头一致）】')
    body = response.json()
    for key in ('trace_id', 'request_id', 'span_id', 'path', 'method'):
        print(f'    {key:12} = {body[key]!r}')

    print('\n  【小结】')
    print('    - trace_id 是 32 位 hex 字符串（uuid4().hex）')
    print('    - 三个 id 长度都是 32，互不相同')
    print('    - 响应头和路由内 ContextVar 读到的是同一个值')


# ============================================================
# 2. CORS 中间件
# ============================================================
def test_cors_middleware_demo():
    """展示 CORS 中间件：预检请求 + 实际跨域请求的响应头"""
    print('\n' + '=' * 70)
    print('中间件 2/4：CORS 中间件（跨域资源共享）')
    print('=' * 70)

    app = _build_app()
    client = TestClient(app)

    # ---- 预检请求 ----
    print('\n→ 场景 A：预检请求（OPTIONS，浏览器跨域前先发）')
    print('    请求头：Origin=http://localhost:5173, '
          'Access-Control-Request-Method=GET')
    response = client.options(
        '/hello',
        headers={
            'Origin': 'http://localhost:5173',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'content-type',
        },
    )
    print(f'\n    状态码：{response.status_code}')
    cors_headers = {
        k: v for k, v in response.headers.items()
        if k.startswith('access-control')
    }
    _print_headers('CORS 相关响应头', cors_headers)

    # ---- 实际跨域请求 ----
    print('\n→ 场景 B：实际跨域请求（GET 带 Origin）')
    response = client.get(
        '/hello',
        headers={'Origin': 'http://localhost:5173'},
    )
    print(f'\n    状态码：{response.status_code}')
    cors_headers = {
        k: v for k, v in response.headers.items()
        if k.startswith('access-control')
    }
    _print_headers('CORS 相关响应头', cors_headers)

    print('\n  【小结】')
    print('    - 预检请求返回 200 + access-control-allow-* 系列头')
    print('    - 实际请求带 Origin 时，响应头里有 access-control-allow-origin')


# ============================================================
# 3. Gzip 中间件
# ============================================================
def test_gzip_middleware_demo():
    """展示 Gzip 中间件：大响应压缩、小响应不压缩"""
    print('\n' + '=' * 70)
    print('中间件 3/4：Gzip 中间件（响应压缩）')
    print('=' * 70)

    app = _build_app()
    # TestClient 默认带 Accept-Encoding: gzip
    client = TestClient(app)

    # ---- 小响应 ----
    print('\n→ 场景 A：小响应（/hello，~200 字节，< minimum_size=1000）')
    response = client.get('/hello')
    raw_size = len(response.content)
    encoding = response.headers.get('content-encoding', '(无)')
    print(f'\n    状态码         : {response.status_code}')
    print(f'    content-encoding : {encoding}')
    print(f'    响应体原始大小   : {raw_size} 字节')
    print(f'    是否被 gzip 压缩 : {"是 ❌（不该压缩）" if encoding == "gzip" else "否 ✅"}')

    # ---- 大响应 ----
    print('\n→ 场景 B：大响应（/big，返回 2000 个 x，> minimum_size=1000）')
    response = client.get('/big')
    raw_size = len(response.content)
    encoding = response.headers.get('content-encoding', '(无)')
    body_data_len = len(response.json()['data'])

    # TestClient 会自动解压，要看压缩后的实际传输大小，需看原始响应
    # 用 response.raw 或者直接看没有解压的流
    print(f'\n    状态码         : {response.status_code}')
    print(f'    content-encoding : {encoding}')
    print(f'    响应体解压后大小 : {raw_size} 字节')
    print(f'    实际 data 长度   : {body_data_len} 字节')
    print(f'    是否被 gzip 压缩 : {"是 ✅" if encoding == "gzip" else "否 ❌"}')

    print('\n  【小结】')
    print('    - minimum_size=1000：小于 1000 字节不压缩')
    print('    - 大响应 content-encoding=gzip，TestClient 自动解压后 json() 仍可用')


# ============================================================
# 4. ContextCleanup 中间件
# ============================================================
def test_context_cleanup_middleware_demo():
    """展示 ContextCleanup 中间件：请求前后 ContextVar 的清理过程"""
    print('\n' + '=' * 70)
    print('中间件 4/4：ContextCleanup 中间件（上下文清理）')
    print('=' * 70)

    app = _build_app()
    client = TestClient(app)

    print('\n→ 请求前：直接读 ContextVar（应为空，因为还没请求）')
    print(f'    trace_id   = {TraceCtx.get_trace_id()!r}')
    print(f'    request_id = {TraceCtx.get_request_id()!r}')
    print(f'    span_id    = {TraceCtx.get_span_id()!r}')

    print('\n→ 发送 GET /hello 请求（路由内会读到 ContextVar 的值）')
    response = client.get('/hello')
    body = response.json()
    print(f'\n    路由内读到的 trace_id = {body["trace_id"]!r}')
    print(f'    响应头 trace-id      = {response.headers.get("trace-id")!r}')

    print('\n→ 请求后：再读 ContextVar（应被 ContextCleanupMiddleware 清理为空）')
    print(f'    trace_id   = {TraceCtx.get_trace_id()!r}'
          f'  ← 应为空串')
    print(f'    request_id = {TraceCtx.get_request_id()!r}'
          f'  ← 应为空串')
    print(f'    span_id    = {TraceCtx.get_span_id()!r}'
          f'  ← 应为空串')

    print('\n→ 连发两次请求，验证每次请求的 trace_id 都不同（不会残留）')
    r1 = client.get('/hello')
    r2 = client.get('/hello')
    print(f'\n    第 1 次 trace-id = {r1.headers.get("trace-id")}')
    print(f'    第 2 次 trace-id = {r2.headers.get("trace-id")}')
    print(f'    两次是否不同     : {r1.headers["trace-id"] != r2.headers["trace-id"]}')

    print('\n  【小结】')
    print('    - 请求前 ContextVar 为空（默认值）')
    print('    - 请求中 Trace 中间件注入 trace_id，路由内能读到')
    print('    - 请求后 ContextCleanupMiddleware.clear() 清空 ContextVar')
    print('    - 清理后下次请求不会读到上次的残留值（防协程间污染）')
