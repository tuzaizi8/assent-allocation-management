from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware


def add_gzip_middleware(app: FastAPI) -> None:
    """
    添加 gzip 压缩中间件

    :param app: FastAPI 对象
    :return: None
    """
    # minimum_size: 小于该字节数的响应不压缩（避免压缩开销 > 收益）
    # compresslevel: 1-9，9 压缩率最高但 CPU 开销最大
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=9)