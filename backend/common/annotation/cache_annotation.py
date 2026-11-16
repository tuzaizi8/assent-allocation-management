"""接口缓存 AOP 注解。

@ApiCache：自动缓存 GET 响应，命中直接返回，未命中执行业务后写入 Redis。
@ApiCacheEvict：写操作成功后清除相关缓存，保证 Cache-Aside 一致性。
"""

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from functools import wraps
from typing import Any, TypeVar

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from redis import asyncio as aioredis
from typing_extensions import ParamSpec

from common.constants import HttpStatusConstant
from core.context_utils import get_current_user_or_none
from utils.log import logger

P = ParamSpec('P')
R = TypeVar('R')

# 缓存 key 前缀（与若依 RedisInitKeyConfig.API_CACHE 对齐）
API_CACHE_PREFIX = 'api_cache'


class ApiCache:
    """接口缓存装饰器，仅用于幂等且返回 JSON 的接口

    示例：
        @ApiCache(namespace='user_list', expire_seconds=30)
        async def get_system_user_list(...): ...
    """

    def __init__(
        self,
        namespace: str,
        expire_seconds: int = 10,
        vary_by_user: bool = True,
        methods: Sequence[str] | None = None,
        cache_response_codes: set[int] | None = None,
    ) -> None:
        """
        :param namespace: 缓存命名空间，用于区分不同接口（如 user_list / role_list）
        :param expire_seconds: 缓存过期时间（秒），默认 10s
        :param vary_by_user: 是否按当前登录用户隔离缓存，默认 True
        :param methods: 允许缓存的 HTTP 方法，默认仅 GET
        :param cache_response_codes: 允许缓存的业务响应码，默认仅 200
        """
        self.namespace = namespace
        self.expire_seconds = expire_seconds
        self.vary_by_user = vary_by_user
        self.methods = tuple(m.upper() for m in (methods or ('GET',)))
        self.cache_response_codes = cache_response_codes or {HttpStatusConstant.SUCCESS}

    def __call__(self, func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # 从参数中提取 Request 与 Redis 连接
            request = self._extract_request(func, *args, **kwargs)
            redis = self._extract_redis(request)
            if request is None or redis is None:
                # Redis 不可用时直接放行，不影响业务
                return await func(*args, **kwargs)

            # 非 GET 请求不缓存
            if request.method.upper() not in self.methods:
                return await func(*args, **kwargs)

            # 生成缓存 key
            cache_key = await self._build_cache_key(request)
            # 查 Redis
            cached_response = await redis.get(cache_key)
            if cached_response:
                # 命中：直接返回缓存响应
                logger.debug(f'[@ApiCache] HIT: {cache_key}')
                return self._build_cached_response(cached_response)  # type: ignore[return-value]

            # 未命中：执行业务方法
            result = await func(*args, **kwargs)
            # 写入 Redis（仅缓存成功响应）
            await self._cache_response(redis, cache_key, result)
            # 标记响应头为 MISS（直接给 Response 对象加 header）
            if hasattr(result, 'headers'):
                result.headers['X-Api-Cache'] = 'MISS'
            return result

        return wrapper

    def _extract_request(self, func: Callable, *args, **kwargs) -> Request | None:
        """从被装饰函数参数中提取 Request"""
        import inspect
        bound = inspect.signature(func).bind(*args, **kwargs)
        bound.apply_defaults()
        for value in bound.arguments.values():
            if isinstance(value, Request):
                return value
        return None

    def _extract_redis(self, request: Request) -> aioredis.Redis | None:
        """从 app.state 中提取 Redis 连接(lifespan 启动时初始化)"""
        return getattr(request.app.state, 'redis', None)

    async def _build_cache_key(self, request: Request) -> str:
        """生成稳定的缓存 key：method + path + path_params + query_params + body_digest + user_scope"""
        request_body = await request.body()
        user_scope = self._get_user_scope(request) if self.vary_by_user else ''
        key_material = {
            'method': request.method,
            'path': request.url.path,
            'path_params': dict(sorted(request.path_params.items())),
            'query_params': sorted(request.query_params.multi_items()),
            'body_digest': hashlib.sha256(request_body).hexdigest() if request_body else '',
            'user_scope': user_scope,
        }
        # 序列化为稳定字符串后整体 hash
        key_digest = hashlib.sha256(
            json.dumps(
                key_material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(',', ':'),
                default=str,
            ).encode('utf-8')
        ).hexdigest()
        return f'{API_CACHE_PREFIX}:{self.namespace}:{key_digest}'

    def _get_user_scope(self, request: Request) -> str:
        """获取用户隔离维度：优先 user_id，未登录回退到 Authorization 摘要"""
        current_user = get_current_user_or_none()
        if current_user:
            return str(current_user.user_id)
        # 未登录场景：用 Authorization 头摘要做隔离
        authorization = request.headers.get('Authorization', '')
        return hashlib.sha256(authorization.encode('utf-8')).hexdigest() if authorization else ''

    async def _cache_response(self, redis: aioredis.Redis, cache_key: str, result: Any) -> None:
        """将响应写入 Redis（仅缓存可序列化的 JSON 响应）"""
        payload = self._extract_response_payload(result)
        if payload is None:
            return
        serialized = json.dumps(payload, ensure_ascii=False)
        # 设置 TTL，避免缓存雪崩
        await redis.set(cache_key, serialized, ex=self.expire_seconds)
        logger.debug(f'[@ApiCache] WRITE: {cache_key}')

    def _extract_response_payload(self, result: Any) -> dict[str, Any] | None:
        """从响应对象中提取可缓存的载荷"""
        # StreamingResponse 不缓存（无法安全复放）
        if isinstance(result, Response) and not isinstance(result, JSONResponse):
            return None
        # JSONResponse：解析 body
        if isinstance(result, JSONResponse):
            content = json.loads(result.body.decode('utf-8'))
            # 仅缓存成功响应
            if not self._is_cacheable(content):
                return None
            return {
                'content': content,
                'status_code': result.status_code,
                'media_type': result.media_type,
                'headers': self._filter_headers(result.headers),
            }
        # 普通对象：用 jsonable_encoder 转换
        content = jsonable_encoder(result)
        if not self._is_cacheable(content):
            return None
        return {
            'content': content,
            'status_code': HttpStatusConstant.SUCCESS,
            'media_type': 'application/json',
            'headers': {},
        }

    def _is_cacheable(self, content: Any) -> bool:
        """判断响应内容是否可缓存（仅缓存 code 在白名单内的响应）"""
        if not isinstance(content, dict):
            return True
        code = content.get('code')
        if code is None:
            return True
        return code in self.cache_response_codes

    def _build_cached_response(self, cached_response: str) -> JSONResponse:
        """根据缓存内容重建 JSONResponse"""
        cached_payload = json.loads(cached_response)
        # 刷新响应中的 time 字段，避免客户端看到旧时间
        content = self._refresh_time(cached_payload['content'])
        response = JSONResponse(
            status_code=cached_payload['status_code'],
            content=jsonable_encoder(content),
            headers=cached_payload.get('headers'),
            media_type=cached_payload.get('media_type'),
        )
        response.headers['X-Api-Cache'] = 'HIT'
        return response

    def _filter_headers(self, headers) -> dict[str, str]:
        """过滤不适合回放的响应头（如 content-length / set-cookie）"""
        excluded = {'content-length', 'content-type', 'set-cookie'}
        return {k: v for k, v in headers.items() if k.lower() not in excluded}

    def _refresh_time(self, content: Any) -> Any:
        """刷新统一响应体中的 time 字段"""
        if isinstance(content, dict) and {'code', 'msg', 'time'}.issubset(content):
            content = content.copy()
            content['time'] = datetime.now()
        return content

    def _merge_header(self, request: Request, headers: dict[str, str]) -> None:
        """合并响应头到 request.state(@ApiRateLimit 用;@ApiCache 直接给 Response 加 header)"""
        existing = getattr(request.state, 'extra_headers', {}) or {}
        existing.update(headers)
        request.state.extra_headers = existing

class ApiCacheEvict:
    """接口缓存失效装饰器，用于在写操作成功后统一清理相关缓存

    遵循 Cache-Aside 模式：先更新数据库，成功后再删除缓存。

    示例：
        @ApiCacheEvict(evict_keys=['user_list', 'user_detail'])
        async def add_user(...): ...
    """

    def __init__(
        self,
        evict_keys: Sequence[str] | None = None,
        evict_all: bool = False,
        evict_response_codes: set[int] | None = None,
    ) -> None:
        """
        :param evict_keys: 需要失效的缓存命名空间列表（如 ['user_list', 'user_detail']）
        :param evict_all: 是否清除所有接口缓存，默认 False
        :param evict_response_codes: 允许触发失效的业务响应码，默认仅成功响应触发
        """
        if not evict_all and not evict_keys:
            raise ValueError('ApiCacheEvict 至少需要指定 evict_keys 或 evict_all=True')
        self.evict_keys = tuple(dict.fromkeys(evict_keys or ()))  # 去重保序
        self.evict_all = evict_all
        self.evict_response_codes = evict_response_codes or {HttpStatusConstant.SUCCESS}

    def __call__(self, func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # 先执行业务方法（Cache-Aside: 先更新 DB）
            result = await func(*args, **kwargs)
            # 从参数中提取 Request 与 Redis
            request = self._extract_request(func, *args, **kwargs)
            redis = self._extract_redis(request) if request else None
            if redis is None:
                return result
            # 仅在业务成功时清除缓存
            if self._should_evict(result):
                await self._evict_cache(redis)
            return result

        return wrapper

    def _extract_request(self, func: Callable, *args, **kwargs) -> Request | None:
        """从被装饰函数参数中提取 Request"""
        import inspect
        bound = inspect.signature(func).bind(*args, **kwargs)
        bound.apply_defaults()
        for value in bound.arguments.values():
            if isinstance(value, Request):
                return value
        return None

    def _extract_redis(self, request: Request) -> aioredis.Redis | None:
        """从 app.state 中提取 Redis 连接"""
        return getattr(request.app.state, 'redis', None)

    def _should_evict(self, result: Any) -> bool:
        """判断当前响应是否应触发缓存失效（仅成功响应触发）"""
        if isinstance(result, JSONResponse):
            content = json.loads(result.body.decode('utf-8'))
            if isinstance(content, dict):
                code = content.get('code')
                if code is None:
                    return True
                return code in self.evict_response_codes
        return True

    async def _evict_cache(self, redis: aioredis.Redis) -> None:
        """执行缓存清除"""
        if self.evict_all:
            # 清除所有接口缓存：SCAN api_cache:*
            pattern = f'{API_CACHE_PREFIX}:*'
            deleted = await self._clear_by_pattern(redis, pattern)
            logger.info(f'[@ApiCacheEvict] 清除全部接口缓存: {deleted} 条')
            return
        # 清除指定命名空间：SCAN api_cache:{namespace}:*
        total_deleted = 0
        for namespace in self.evict_keys:
            pattern = f'{API_CACHE_PREFIX}:{namespace}:*'
            total_deleted += await self._clear_by_pattern(redis, pattern)
        logger.info(f'[@ApiCacheEvict] 清除命名空间 {self.evict_keys} 缓存: {total_deleted} 条')

    async def _clear_by_pattern(self, redis: aioredis.Redis, pattern: str) -> int:
        """通过 SCAN 模式匹配并删除缓存 key"""
        count = 0
        batch: list[str] = []
        async for key in redis.scan_iter(match=pattern, count=100):
            batch.append(key)
            if len(batch) >= 100:
                count += await redis.delete(*batch)
                batch.clear()
        if batch:
            count += await redis.delete(*batch)
        return count