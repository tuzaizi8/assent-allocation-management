from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def add_cors_middleware(app: FastAPI) -> None:
    """
    添加跨域中间件

    :param app: FastAPI 对象
    :return: None
    """
    # 前端页面允许的源，生产环境必须改为明确的前端域名列表，['http://localhost:3000', 'https://your-domain.com']
    origins = ['http://localhost:3000']
    # 允许前端 JavaScript 读取的自定义响应头
    expose_headers = [
        'trace-id',
        'request-id',
        'span-id',
    ]

    # 后台 API 允许跨域
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
        expose_headers=expose_headers,
    )