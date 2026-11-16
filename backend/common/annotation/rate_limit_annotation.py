"""接口限流 AOP 注解。

@ApiRateLimit：基于 Redis Lua 脚本的接口限流，支持固定窗口 / 滑动窗口两种算法。
固定窗口：INCR + PEXPIRE
滑动窗口：ZSET + ZREMRANGEBYSCORE + ZADD + ZCARD
"""

import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from functools import wraps
from typing import Literal, TypeVar

from fastapi import Request
from redis import asyncio as aioredis
from typing_extensions import ParamSpec

from core.context_utils import get_current_user_or_none
from utils.client_ip_util import ClientIPUtil
from utils.log import logger
from utils.response_util import ResponseUtil

P = ParamSpec('P')
R = TypeVar('R')

RateLimitScope = Literal['ip', 'user']
RateLimitAlgorithm = Literal['fixed_window', 'sliding_window']

# 限流 key 前缀
API_RATE_LIMIT_PREFIX = 'api_rate_limit'

# 固定窗口 Lua 脚本：INCR + PEXPIRE
_FIXED_WINDOW_LUA_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
local ttl = redis.call('PTTL', KEYS[1])
if current == 1 or ttl < 0 then
    redis.call('PEXPIRE', KEYS[1], ARGV[1])
    ttl = redis.call('PTTL', KEYS[1])
end
local limit = tonumber(ARGV[2])
local remaining = limit - current
if remaining < 0 then
    remaining = 0
end
local allowed = 0
if current <= limit then
    allowed = 1
end
return {allowed, current, remaining, ttl}
"""

# 滑动窗口 Lua 脚本：ZSET + ZREMRANGEBYSCORE + ZADD + ZCARD
_SLIDING_WINDOW_LUA_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, tonumber(ARGV[1]) - tonumber(ARGV[2]))
local current = redis.call('ZCARD', KEYS[1])
local limit = tonumber(ARGV[4])
local ttl = ARGV[2]
if current >= limit then
    local earliest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    if earliest[2] ~= nil then
        ttl = tonumber(ARGV[2]) - (tonumber(ARGV[1]) - tonumber(earliest[2]))
    end
    if ttl < 1 then
        ttl = 1
    end
    return {0, current, 0, ttl}
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[3])
redis.call('PEXPIRE', KEYS[1], ARGV[2])
current = current + 1
local remaining = limit - current
if remaining < 0 then
    remaining = 0
end
local earliest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
if earliest[2] ~= nil then
    ttl = tonumber(ARGV[2]) - (tonumber(ARGV[1]) - tonumber(earliest[2]))
end
if ttl < 1 then
    ttl = 1
end
return {1, current, remaining, ttl}
"""


class ApiRateLimit:
    """接口限流装饰器，基于 Redis Lua 脚本实现

    示例：
        @ApiRateLimit(namespace='login', limit=12, period=60, algorithm='sliding_window')
        async def login(...): ...
    """

    def __init__(
        self,
        namespace: str,
        limit: int,
        period: int,
        scope: RateLimitScope = 'ip',
        algorithm: RateLimitAlgorithm = 'fixed_window',
        methods: Sequence[str] | None = None,
        message: str = '请求过于频繁，请稍后再试',
    ) -> None:
        """
        :param namespace: 限流命名空间（如 login / register / captcha）
        :param limit: 时间窗口内允许的最大请求次数
        :param period: 时间窗口大小（秒）
        :param scope: 限流作用域，ip 按客户端 IP，user 按当前登录用户
        :param algorithm: 限流算法，fixed_window 固定窗口 / sliding_window 滑动窗口
        :param methods: 需要限流的 HTTP 方法，None 表示所有限流
        :param message: 触发限流后的提示信息
        """
        if not namespace:
            raise ValueError('ApiRateLimit 的 namespace 不能为空')
        if limit <= 0:
            raise ValueError('ApiRateLimit 的 limit 必须大于 0')
        if period <= 0:
            raise ValueError('ApiRateLimit 的 period 必须大于 0')
        self.namespace = namespace
        self.limit = limit
        self.period = period
        self.scope = scope
        self.algorithm = algorithm
        self.methods = tuple(m.upper() for m in methods) if methods else None
        self.message = message

    def __call__(self, func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            request = self._extract_request(func, *args, **kwargs)
            if request is None:
                return await func(*args, **kwargs)
            # 不限流的方法直接放行
            if self.methods and request.method.upper() not in self.methods:
                return await func(*args, **kwargs)

            redis = getattr(request.app.state, 'redis', None)
            if redis is None:
                # Redis 不可用时放行（fail-open）
                logger.warning('[@ApiRateLimit] Redis 不可用，放行请求')
                return await func(*args, **kwargs)

            # 执行限流判断
            try:
                rate_limit_result = await self._acquire_rate_limit(redis, request)
            except Exception as exc:
                logger.warning(f'[@ApiRateLimit] Lua 执行异常，放行请求: {exc}')
                return await func(*args, **kwargs)

            if not rate_limit_result['allowed']:
                # 超限：返回 429
                logger.warning(
                    f'[@ApiRateLimit] 限流命中: namespace={self.namespace} '
                    f'method={request.method} path={request.url.path} '
                    f'current={rate_limit_result["current"]} limit={self.limit}'
                )
                headers = self._build_headers(rate_limit_result)
                return ResponseUtil.too_many_requests(msg=self.message, headers=headers)  # type: ignore[return-value]

            # 放行：执行业务方法，并把限流响应头直接写入 Response 对象
            # （不再用 request.state.extra_headers 中转，避免 ResponseUtil 未读取导致头丢失）
            result = await func(*args, **kwargs)
            if hasattr(result, 'headers'):
                for key, value in self._build_headers(rate_limit_result).items():
                    result.headers[key] = value
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

    async def _acquire_rate_limit(self, redis: aioredis.Redis, request: Request) -> dict:
        """执行 Lua 脚本获取限流结果"""
        current_time_ms = int(time.time() * 1000)
        rate_limit_key = self._build_rate_limit_key(request, current_time_ms)

        if self.algorithm == 'sliding_window':
            allowed, current, remaining, reset_after_ms = await redis.eval(
                _SLIDING_WINDOW_LUA_SCRIPT,
                1,
                rate_limit_key,
                current_time_ms,                       # ARGV[1]: 当前时间戳（毫秒）
                self.period * 1000,                    # ARGV[2]: 窗口大小（毫秒）
                f'{current_time_ms}-{time.time_ns()}',  # ARGV[3]: 唯一成员标识
                self.limit,                            # ARGV[4]: 限流阈值
            )
        else:
            window_ms = self.period * 1000
            window_bucket = current_time_ms // window_ms
            window_end_ms = (window_bucket + 1) * window_ms
            ttl_ms = max(window_end_ms - current_time_ms, 1)
            allowed, current, remaining, reset_after_ms = await redis.eval(
                _FIXED_WINDOW_LUA_SCRIPT,
                1,
                rate_limit_key,
                ttl_ms,      # ARGV[1]: TTL（毫秒）
                self.limit,  # ARGV[2]: 限流阈值
            )

        reset_after_ms = max(int(reset_after_ms), 1)
        return {
            'allowed': bool(int(allowed)),
            'current': int(current),
            'remaining': int(remaining),
            'reset_after_seconds': max((reset_after_ms + 999) // 1000, 1),
        }

    def _build_rate_limit_key(self, request: Request, current_time_ms: int) -> str:
        """构建限流 key。

        :return: 限流 key 字符串（不再返回 None，未登录场景由 _get_scope_value 回退到 IP）
        """
        scope_value = self._get_scope_value(request)
        key_material = {
            'method': request.method.upper(),
            'path': request.url.path,
            'scope': self.scope,
            'scope_value': scope_value,
        }
        key_digest = hashlib.sha256(
            json.dumps(
                key_material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(',', ':'),
            ).encode('utf-8')
        ).hexdigest()
        key_prefix = f'{API_RATE_LIMIT_PREFIX}:{self.namespace}:{self.algorithm}:{key_digest}'
        # 固定窗口需要带窗口桶，保证每个窗口独立计数
        if self.algorithm == 'fixed_window':
            window_bucket = current_time_ms // (self.period * 1000)
            return f'{key_prefix}:{window_bucket}'
        return key_prefix

    def _get_scope_value(self, request: Request) -> str:
        """获取限流作用域值。

        - scope='ip':按客户端 IP 限流
        - scope='user':按当前登录用户 user_id 限流;未登录回退到 IP 限流,
          避免攻击者不带 token 绕过限流。

        :return: 限流作用域值字符串
        """
        if self.scope == 'ip':
            return f'ip:{ClientIPUtil.get_client_ip(request)}'
        # scope == 'user'
        current_user = get_current_user_or_none()
        if current_user :
            return f'user:{current_user.user_id}'
        # 未登录用户回退到 IP 限流，避免匿名请求绕过限流
        logger.debug('[@ApiRateLimit] scope=user 但当前未登录，回退到 IP 限流')
        return f'ip:{ClientIPUtil.get_client_ip(request)}'

    def _build_headers(self, rate_limit_result: dict) -> dict[str, str]:
        """构建限流响应头"""
        headers = {
            'X-RateLimit-Limit': str(self.limit),
            'X-RateLimit-Remaining': str(rate_limit_result['remaining']),
            'X-RateLimit-Reset': str(rate_limit_result.get('reset_after_seconds', self.period)),
        }
        if not rate_limit_result['allowed']:
            headers['Retry-After'] = str(rate_limit_result.get('reset_after_seconds', self.period))
        return headers