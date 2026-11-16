"""响应工具类

- success: 成功（code=200, HTTP 200）
- failure: 业务失败（code=601, HTTP 200）
- unauthorized: 未认证（code=401, HTTP 200）
- forbidden: 禁止访问（code=403, HTTP 200）
- error: 系统错误（code=500, HTTP 200）
- too_many_requests: 限流（code=429, HTTP 429,唯一返回真实 HTTP 错误码）
- streaming: 流式响应（SSE / 文件流）

设计原则：业务错误一律 HTTP 200 + body code，
仅限流用真实 HTTP 429（基础设施语义，让网关/CDN 可识别）。
"""
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fastapi import status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from common.constants import HttpStatusConstant


class ResponseUtil:
    """响应工具类

    所有方法都是 classmethod，无需实例化，直接 ResponseUtil.success(...) 调用。
    所有方法返回 starlette.Response（JSONResponse / StreamingResponse），
    可直接作为 FastAPI 路由返回值。
    """

    @classmethod
    def success(
        cls,
        msg: str = '操作成功',
        data: Any | None = None,
        rows: Any | None = None,
        dict_content: dict | None = None,
        model_content: BaseModel | None = None,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> Response:
        """成功响应

        :param msg: 自定义成功信息
        :param data: 单对象数据（放入 data 字段）
        :param rows: 列表数据（放入 rows 字段，分页场景）
        :param dict_content: 自定义 dict，会 update 到响应体
        :param model_content: Pydantic 模型，model_dump(by_alias=True) 后 update
        :param headers: 响应头
        :param media_type: 媒体类型
        :param background: 响应返回后执行的后台任务
        :return: JSONResponse（HTTP 200, code=200）
        """
        result = {'code': HttpStatusConstant.SUCCESS, 'msg': msg}

        if data is not None:
            result['data'] = data
        if rows is not None:
            result['rows'] = rows
        if dict_content is not None:
            result.update(dict_content)
        if model_content is not None:
            result.update(model_content.model_dump(by_alias=True))

        result.update({'success': True, 'time': datetime.now()})

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder(result),
            headers=headers,
            media_type=media_type,
            background=background,
        )

    @classmethod
    def failure(
        cls,
        msg: str = '操作失败',
        data: Any | None = None,
        rows: Any | None = None,
        dict_content: dict | None = None,
        model_content: BaseModel | None = None,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> Response:
        """业务失败响应（code=601, HTTP 200）

        用于参数校验失败、资源不存在、业务规则不允许等场景。
        """
        result = {'code': HttpStatusConstant.WARN, 'msg': msg}

        if data is not None:
            result['data'] = data
        if rows is not None:
            result['rows'] = rows
        if dict_content is not None:
            result.update(dict_content)
        if model_content is not None:
            result.update(model_content.model_dump(by_alias=True))

        result.update({'success': False, 'time': datetime.now()})

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder(result),
            headers=headers,
            media_type=media_type,
            background=background,
        )

    @classmethod
    def unauthorized(
        cls,
        msg: str = '登录信息已过期，访问系统资源失败',
        data: Any | None = None,
        rows: Any | None = None,
        dict_content: dict | None = None,
        model_content: BaseModel | None = None,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> Response:
        """未认证响应（code=401, HTTP 200）

        用于未登录或 token 过期。
        """
        result = {'code': HttpStatusConstant.UNAUTHORIZED, 'msg': msg}

        if data is not None:
            result['data'] = data
        if rows is not None:
            result['rows'] = rows
        if dict_content is not None:
            result.update(dict_content)
        if model_content is not None:
            result.update(model_content.model_dump(by_alias=True))

        result.update({'success': False, 'time': datetime.now()})

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder(result),
            headers=headers,
            media_type=media_type,
            background=background,
        )

    @classmethod
    def forbidden(
        cls,
        msg: str = '该用户无此接口权限',
        data: Any | None = None,
        rows: Any | None = None,
        dict_content: dict | None = None,
        model_content: BaseModel | None = None,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> Response:
        """禁止访问响应（code=403, HTTP 200）

        用于已登录但无权限访问该接口。
        """
        result = {'code': HttpStatusConstant.FORBIDDEN, 'msg': msg}

        if data is not None:
            result['data'] = data
        if rows is not None:
            result['rows'] = rows
        if dict_content is not None:
            result.update(dict_content)
        if model_content is not None:
            result.update(model_content.model_dump(by_alias=True))

        result.update({'success': False, 'time': datetime.now()})

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder(result),
            headers=headers,
            media_type=media_type,
            background=background,
        )

    @classmethod
    def error(
        cls,
        msg: str = '接口异常',
        data: Any | None = None,
        rows: Any | None = None,
        dict_content: dict | None = None,
        model_content: BaseModel | None = None,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> Response:
        """系统错误响应（code=500, HTTP 200）

        用于未捕获的异常。注意：仍是 HTTP 200，前端通过 code=500 判断。
        """
        result = {'code': HttpStatusConstant.ERROR, 'msg': msg}

        if data is not None:
            result['data'] = data
        if rows is not None:
            result['rows'] = rows
        if dict_content is not None:
            result.update(dict_content)
        if model_content is not None:
            result.update(model_content.model_dump(by_alias=True))

        result.update({'success': False, 'time': datetime.now()})

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder(result),
            headers=headers,
            media_type=media_type,
            background=background,
        )

    @classmethod
    def too_many_requests(
        cls,
        msg: str = '请求过于频繁，请稍后再试',
        data: Any | None = None,
        rows: Any | None = None,
        dict_content: dict | None = None,
        model_content: BaseModel | None = None,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> Response:
        """限流响应（code=429, HTTP 429）

        唯一同时返回真实 HTTP 错误码的方法。
        HTTP 429 是基础设施层语义，让 Nginx/CDN/APM 可识别限流。
        """
        result = {'code': HttpStatusConstant.TOO_MANY_REQUESTS, 'msg': msg}

        if data is not None:
            result['data'] = data
        if rows is not None:
            result['rows'] = rows
        if dict_content is not None:
            result.update(dict_content)
        if model_content is not None:
            result.update(model_content.model_dump(by_alias=True))

        result.update({'success': False, 'time': datetime.now()})

        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=jsonable_encoder(result),
            headers=headers,
            media_type=media_type,
            background=background,
        )

    @classmethod
    def streaming(
        cls,
        *,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> Response:
        """流式响应

        用于 SSE（Server-Sent Events）、文件下载、大模型流式输出等场景。
        注意：用关键字参数（*），强制调用方写 data=..., 避免位置参数歧义。

        :param data: 可迭代的流式内容（生成器 / 异步生成器）
        :param headers: 响应头
        :param media_type: 媒体类型（SSE 用 'text/event-stream'）
        :param background: 后台任务
        :return: StreamingResponse（HTTP 200, chunked）
        """
        return StreamingResponse(
            status_code=status.HTTP_200_OK,
            content=data,
            headers=headers,
            media_type=media_type,
            background=background,
        )