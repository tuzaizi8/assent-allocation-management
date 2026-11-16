import os
import re
import sys

from loguru import logger

from config.settings import LogConfig

from middlewares.trace_middleware import TraceCtx

# 日志目录
LOG_DIR = os.path.join(os.getcwd(), LogConfig.log_dir)
os.makedirs(LOG_DIR, exist_ok=True)

# 移除 loguru 默认 handler
logger.remove()

logger.configure(
    extra={'trace_id': '-'},  # 默认值:非请求上下文(启动日志)时显示占位符
    patcher=lambda record: record['extra'].update(
        trace_id=TraceCtx.get_trace_id() or '-'
    ),
)

def _mask_value(key: str, value: str) -> str:
    """对敏感字段值进行脱敏

    Args:
        key: 字段名
        value: 原始值

    Returns:
        脱敏后的值
    """
    key_lower = key.lower()

    # 完整脱敏：password/token/secret 等
    for field in LogConfig.mask_fields_list:
        if field in key_lower:
            return '***'

    # 部分脱敏：phone/email/id_card 等
    for field in LogConfig.partial_mask_fields_list:
        if field in key_lower:
            if not value or len(value) <= 2:
                return '*' * len(value)
            # 保留首尾，中间用 * 替换
            mask_len = min(len(value) - 2, 4)
            return f'{value[0]}{"*" * mask_len}{value[-1]}'

    return value

def _sensitive_filter(record):
    """日志脱敏过滤器

    在日志记录写入前，对 message 中的敏感信息进行脱敏。
    注意：loguru 的 filter 返回 truthy 值才输出日志，返回 None/falsy 会丢弃日志。
    """
    message = record['message']
    if message:
        # 匹配 JSON 格式的键值对：{"password": "mysqlroot", "phone": "13812345678"}
        def replace_match(match):
            key = match.group(1)
            value = match.group(2)
            masked = _mask_value(key, value)
            return f'"{key}": "{masked}"'

        # 正则匹配 "key": "value" 格式
        pattern = r'"([^"]+)":\s*"([^"]*)"'
        record['message'] = re.sub(pattern, replace_match, message)

    return True  # 必须返回 True，否则日志会被丢弃

# ========== 1. 控制台输出 ==========
logger.add(
    sys.stdout,
    level=LogConfig.log_level,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{extra[trace_id]}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    colorize=True,
    filter=_sensitive_filter,
    # 安全加固:loguru 默认 diagnose=True,异常时会转储局部变量树——
    # 曾把 LoginModel 明文密码与完整 JWT 打进日志(脱敏正则拦不住单引号 repr 格式)
    diagnose=False,
)

# ========== 2. 文件输出（全部日志，按日期切割）==========
logger.add(
    os.path.join(LOG_DIR, '{time:YYYY-MM-DD}.log'),
    level=LogConfig.log_level,
    rotation=LogConfig.log_rotation,
    retention=LogConfig.log_retention,
    compression=LogConfig.log_compression,
    format='{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[trace_id]} | {name}:{function}:{line} - {message}',
    encoding='utf-8',
    filter=_sensitive_filter,
    diagnose=False,
)

# ========== 3. 错误日志单独文件 ==========
logger.add(
    os.path.join(LOG_DIR, 'error_{time:YYYY-MM-DD}.log'),
    level='ERROR',
    rotation=LogConfig.log_rotation,
    retention='90 days',
    compression=LogConfig.log_compression,
    format='{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[trace_id]} | {name}:{function}:{line} - {message}',
    encoding='utf-8',
    filter=_sensitive_filter,
    diagnose=False,
)

__all__ = ['logger']
