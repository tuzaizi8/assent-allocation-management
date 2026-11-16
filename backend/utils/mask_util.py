"""敏感信息脱敏工具。

供操作日志落库前对响应体做敏感键脱敏（与 utils/log.py 的日志文件脱敏同语义：
小写化后子串包含匹配，键集合来自 LogConfig.mask_fields_list）。
"""

import json
import re

from config.settings import LogConfig

MASKED_VALUE = '***'

# JSON 字符串级回退用正则（同 utils/log.py 的 _sensitive_filter 模式）
_KV_PATTERN = re.compile(r'"([^"]+)":\s*"([^"]*)"')


def is_sensitive_key(key: str) -> bool:
    """判断键名是否敏感（小写化后与脱敏字段列表做子串包含匹配）。

    子串匹配可顺带覆盖 accessToken / refresh_token 等变体。
    """
    key_lower = key.lower()
    return any(field.lower() in key_lower for field in LogConfig.mask_fields_list)


def mask_sensitive_obj(obj):
    """递归脱敏：dict 命中敏感键的值置 '***'，嵌套 dict/list 继续深入。"""
    if isinstance(obj, dict):
        return {
            k: (MASKED_VALUE if is_sensitive_key(str(k)) else mask_sensitive_obj(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [mask_sensitive_obj(item) for item in obj]
    return obj


def mask_json_text(text: str) -> str:
    """对已序列化的 JSON 文本做敏感键脱敏。

    优先走结构化路径（loads → 递归 mask → dumps）；
    解析失败时回退到字符串级正则替换（与日志文件脱敏同款模式）。
    """
    if not text:
        return text
    try:
        return json.dumps(mask_sensitive_obj(json.loads(text)), ensure_ascii=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        return _KV_PATTERN.sub(
            lambda m: f'"{m.group(1)}": "{MASKED_VALUE}"' if is_sensitive_key(m.group(1)) else m.group(0),
            text,
        )
