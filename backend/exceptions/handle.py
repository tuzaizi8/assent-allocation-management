"""全局异常处理器

通过 FastAPI 的 @app.exception_handler 装饰器注册各类异常处理器，
将业务异常统一转换为 ResponseUtil 标准响应。

用法（在应用工厂中）：
    from fastapi import FastAPI
    from exceptions.handle import handle_exception

    app = FastAPI()
    handle_exception(app)
"""
from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from exceptions.exceptions import (
    AuthException,
    LoginException,
    ModelValidatorException,
    PermissionException,
    ServiceException,
    ServiceWarning,
)
from utils.log import logger
from utils.response_util import ResponseUtil


def handle_exception(app: FastAPI) -> None:
    """注册全局异常处理器

    在 FastAPI 应用实例上注册 7 个异常处理器：
    - AuthException → 401 未认证
    - LoginException → 601 失败
    - ModelValidatorException → 601 校验失败（warning 日志）
    - PermissionException → 403 禁止
    - ServiceException → 500 错误（error 日志）
    - ServiceWarning → 601 警告（warning 日志）
    - HTTPException → 原生处理
    - Exception → 500 兜底（exception 日志）

    :param app: FastAPI 应用实例
    """

    # 1. 自定义 token 认证异常
    @app.exception_handler(AuthException)
    async def auth_exception_handler(request: Request, exc: AuthException) -> Response:
        """token 过期/无效 → 401"""
        logger.warning(f"[401] {request.method} {request.url.path} | {exc.message}")
        return ResponseUtil.unauthorized(data=exc.data, msg=exc.message)

    # 2. 自定义登录异常
    @app.exception_handler(LoginException)
    async def login_exception_handler(request: Request, exc: LoginException) -> Response:
        """登录失败 → 601"""
        logger.warning(f"[601-登录] {request.method} {request.url.path} | {exc.message}")
        return ResponseUtil.failure(data=exc.data, msg=exc.message)

    # 3. 自定义模型校验异常
    @app.exception_handler(ModelValidatorException)
    async def model_validator_exception_handler(
        request: Request, exc: ModelValidatorException
    ) -> Response:
        """模型校验失败 → 601 + warning 日志"""
        logger.warning(f'[601-校验] {request.method} {request.url.path} | {exc.message}')
        return ResponseUtil.failure(data=exc.data, msg=exc.message)

    # 4. 自定义权限异常
    @app.exception_handler(PermissionException)
    async def permission_exception_handler(
        request: Request, exc: PermissionException
    ) -> Response:
        """无权限 → 403"""
        logger.warning(f"[403] {request.method} {request.url.path} | {exc.message}")
        return ResponseUtil.forbidden(data=exc.data, msg=exc.message)

    # 5. 自定义服务异常
    @app.exception_handler(ServiceException)
    async def service_exception_handler(
        request: Request, exc: ServiceException
    ) -> Response:
        """服务异常 → 500 + error 日志"""
        logger.error(f'[500] {request.method} {request.url.path} | {exc.message}')
        return ResponseUtil.error(data=exc.data, msg=exc.message)

    # 6. 自定义服务警告
    @app.exception_handler(ServiceWarning)
    async def service_warning_handler(request: Request, exc: ServiceWarning) -> Response:
        """服务警告 → 601 + warning 日志"""
        logger.warning(f'[601] {request.method} {request.url.path} | {exc.message}')
        return ResponseUtil.failure(data=exc.data, msg=exc.message)

    # 7. 处理 FastAPI 原生 HTTPException
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        """HTTPException → 保留原生状态码"""
        logger.warning(f"[HTTP{exc.status_code}] {request.method} {request.url.path} | {exc.detail}")
        return JSONResponse(
            content=jsonable_encoder({'code': exc.status_code, 'msg': exc.detail}),
            status_code=exc.status_code,
        )

    # 8. 兜底：所有未捕获的异常
    @app.exception_handler(Exception)
    async def exception_handler(request: Request, exc: Exception) -> Response:
        """未知异常 → 500 + exception 日志（含完整堆栈）"""
        logger.exception(exc)
        return ResponseUtil.error(msg=str(exc))