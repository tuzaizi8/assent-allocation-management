"""操作日志 AOP 注解。

通过 @Log 装饰器在 Controller 方法上声明式接入操作日志，
支持 BEFORE（前置）/ AFTER（后置）/ AROUND（环绕）三种时机，
以及 OTHER / INSERT / UPDATE / DELETE / GRANT / EXPORT / IMPORT 等业务类型。
"""

import inspect
import json
import time
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Awaitable, Callable, TypeVar

from fastapi import Request
from typing_extensions import ParamSpec

from common.constants import LogCategory
from core.context_utils import get_current_user_or_none
from utils.client_ip_util import ClientIPUtil
from utils.mask_util import mask_json_text
from module_system.service.oper_log_service import enqueue_oper_log
from utils.log import logger

# json_result 存储上限(字符):2KB 够看摘要(响应头/前几行),拒绝存全量响应体
# (实测单条曾达 734687223 字符 ≈ 700MB,列表接口 SELECT 大字段物化即秒级慢查询)
MAX_JSON_RESULT_LENGTH = 2000

P = ParamSpec('P')
R = TypeVar('R')


class BusinessType(Enum):
    """业务操作类型（与若依保持一致的语义）"""

    OTHER = 0       # 其它
    INSERT = 1      # 新增
    UPDATE = 2      # 修改
    DELETE = 3      # 删除
    GRANT = 4       # 授权
    EXPORT = 5      # 导出
    IMPORT = 6      # 导入
    FORCE = 7       # 强退
    GENCODE = 8     # 生成代码
    CLEAN = 9       # 清空数据
    QUERY = 10      # 查询(项目扩展:查询类接口也记日志,与写操作区分)


class LogMode(str, Enum):
    """日志记录时机"""

    BEFORE = 'before'   # 前置：方法执行前记录请求
    AFTER = 'after'     # 后置：方法执行后记录请求 + 响应
    AROUND = 'around'   # 环绕：前后都记录，含耗时与异常


class Log:
    """操作日志装饰器（类装饰器，带参数）

    示例：
        @Log(title='用户管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
        async def add_user(...): ...
    """

    def __init__(
        self,
        title: str,
        business_type: BusinessType = BusinessType.OTHER,
        mode: LogMode = LogMode.AROUND,
        category: str = LogCategory.OPERATION,
    ) -> None:
        """
        :param title: 模块标题（如「用户管理」）
        :param business_type: 业务类型（INSERT / UPDATE / DELETE 等）
        :param mode: 日志记录时机（BEFORE / AFTER / AROUND）
        :param category: 日志类别（operation 操作日志 / login 登录日志）
        """
        self.title = title
        self.business_type = business_type
        self.mode = mode
        self.category = category

    def __call__(self, func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start_time = time.perf_counter()
            # 从函数参数中提取 Request 对象
            request = self._extract_request(func, *args, **kwargs)
            # 构造操作日志基础信息
            oper_log = self._build_oper_log_base(func, request)

            # BEFORE 模式：执行前先落一条日志
            if self.mode == LogMode.BEFORE:
                await self._record_log(oper_log, result=None, cost_ms=0, status=0, error_msg='')
                return await func(*args, **kwargs)

            # AFTER / AROUND 模式：执行业务方法并捕获结果与异常
            status = 0
            error_msg = ''
            result = None
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                status = 1
                error_msg = str(exc)
                logger.exception(f'@Log 捕获到业务异常: {exc}')
                raise  # 重新抛出，让 FastAPI 异常处理接管
            finally:
                cost_ms = int((time.perf_counter() - start_time) * 1000)
                oper_log['cost_time'] = cost_ms
                # 登录日志 operName 回填(9.8 ⑩):登录逻辑成功后经 request.state
                # 传递用户名——@Log 在鉴权前记录,login 类日志 operName 恒为 anonymous
                override = getattr(request.state, 'log_oper_name', None)
                if override:
                    oper_log['oper_name'] = override
                # AFTER / AROUND 模式：执行后落日志
                if self.mode in (LogMode.AFTER, LogMode.AROUND):
                    await self._record_log(
                        oper_log, result=result, cost_ms=cost_ms, status=status, error_msg=error_msg
                    )
            return result  # type: ignore[return-value]

        return wrapper

    def _extract_request(self, func: Callable, *args, **kwargs) -> Request:
        """从被装饰函数的参数中提取 Request 对象"""
        bound = inspect.signature(func).bind(*args, **kwargs)
        bound.apply_defaults()
        for name, value in bound.arguments.items():
            if isinstance(value, Request):
                return value
        raise ValueError('@Log 装饰的方法必须包含 Request 类型参数')

    def _build_oper_log_base(self, func: Callable, request: Request) -> dict:
        """构造操作日志的基础字段（不含响应结果与耗时）"""
        # 获取被装饰函数的完整路径（模块.函数名）
        module = inspect.getmodule(func)
        module_path = module.__name__ if module else ''
        func_path = f'{module_path}.{func.__name__}()'

        # 提取请求信息
        oper_ip = ClientIPUtil.get_client_ip(request)
        oper_url = request.url.path
        request_method = request.method

        # 提取当前登录用户（无登录场景时为匿名）
        oper_name = 'anonymous'
        dept_name = None
        current_user = get_current_user_or_none()
        if current_user:
            oper_name = current_user.user_name

        # 提取请求参数（path / query / body）
        oper_param = self._extract_request_params(request)

        return {
            "title": self.title,
            "business_type": self.business_type.value,
            "method": func_path,
            "request_method": request_method,
            "oper_name": oper_name,
            "dept_name": dept_name,
            "oper_url": oper_url,
            "oper_ip": oper_ip,
            "oper_param": oper_param,
            "oper_time": datetime.now(),
            "category": self.category,
        }

    def _extract_request_params(self, request: Request) -> str:
        """提取请求参数并序列化为 JSON 字符串"""
        params: dict = {}
        # 路径参数
        if request.path_params:
            params['path_params'] = dict(request.path_params)
        # 查询参数
        if request.query_params:
            params['query_params'] = dict(request.query_params)
        # 请求体（仅同步读取一次，避免与 FastAPI body 解析冲突）
        # 实际项目中需要通过 Body dependency 或 background task 拿到
        return json.dumps(params, ensure_ascii=False, default=str)

    def _serialize_result(self, result: object) -> str:
        """序列化响应结果为 JSON 字符串（用于 jsonResult 字段,先脱敏后截断）"""
        if result is None:
            return ''
        serialized = ''
        # JSONResponse：直接读 body
        if hasattr(result, 'body'):
            try:
                serialized = result.body.decode('utf-8')
            except Exception:
                return ''
        # 普通对象：用 json.dumps 序列化
        else:
            try:
                serialized = json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                return ''
        # 敏感键脱敏(安全修复):登录/注册响应含有效 JWT、列表响应可能含密码哈希,
        # 日志管理页会全量回读该字段——入库前统一置 '***'。
        # 必须在截断前执行:先截断会把敏感值切残,绕过键值匹配
        serialized = mask_json_text(serialized)
        # 截断:json_result 只存摘要——完整响应体曾把单行
        # 撑到 7 亿字符(查日志接口的自增长尾:响应体又被存为新日志,滚雪球)
        if len(serialized) > MAX_JSON_RESULT_LENGTH:
            return (
                serialized[:MAX_JSON_RESULT_LENGTH]
                + f'...[截断,原 {len(serialized)} 字符]'
            )
        return serialized

    async def _record_log(
        self,
        oper_log: dict,
        result: object,
        cost_ms: int,
        status: int,
        error_msg: str,
    ) -> None:
        """记录操作日志:入内存队列(后台任务写库),同时打摘要日志"""
        oper_log["json_result"] = self._serialize_result(result)
        oper_log["status"] = status
        oper_log["error_msg"] = error_msg
        oper_log["cost_time"] = cost_ms
        # 实际项目中应入队：await LogQueueService.enqueue_operation_log(request, oper_log)
        # B2:非阻塞入队,后台消费写 sys_oper_log
        enqueue_oper_log(dict(oper_log))
        logger.info(
            f"[@Log] {oper_log['title']} | {oper_log['business_type']} | {oper_log['oper_name']} | "
            f"{oper_log['oper_url']} | cost={cost_ms}ms | status={status}"
        )