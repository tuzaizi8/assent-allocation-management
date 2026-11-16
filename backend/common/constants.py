"""
响应码常量

设计原则：业务错误（认证/授权/系统异常）用 body 中的 code 区分，
仅限流场景同时返回真实 HTTP 429（基础设施层语义）。
"""

from common.enums import RedisInitKeyConfig

class HttpStatusConstant:
    """返回状态码

    SUCCESS: 操作成功
    WARN: 系统警告消息（业务失败，如参数校验未过、资源不存在）
    UNAUTHORIZED: 未认证（未登录 / token 过期）
    FORBIDDEN: 禁止访问（已登录但无权限）
    ERROR: 系统内部错误（未捕获异常）
    TOO_MANY_REQUESTS: 请求过于频繁（限流，唯一同时返回真实 HTTP 429 的场景）
    """

    SUCCESS = 200
    WARN = 601
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    ERROR = 500
    TOO_MANY_REQUESTS = 429

class CommonConstant:
    """通用业务常量。

    用于业务层之间的语义化返回值，避免到处出现魔数（magic number）。
    """

    # 唯一性校验
    UNIQUE = True          # 唯一
    NOT_UNIQUE = False     # 已存在（不唯一）

    # 逻辑删除标记
    NORMAL = '0'           # 正常
    DELETED = '2'          # 已删除


# 权限体系锚点:CheckUserInterfaceAuth 与菜单可见性按 role_key 通配放行
# 收常量而非入字典——字典项可被界面删改,权限锚点被改等于整套 RBAC 崩塌
ADMIN_ROLE_KEY = 'admin'

# 登录会话键 login_tokens:{user_id}:写入在登录、校验在鉴权依赖(core/security)与 /auth/me、
# 删除在登出与改密。收在公共常量而非 auth_service —— 鉴权依赖也要用它,
# 放服务层会让 core 反向依赖 service 层
LOGIN_TOKEN_KEY = f'{RedisInitKeyConfig.LOGIN_TOKEN.key}:{{user_id}}'

# 净值/行情新鲜度的每日失效时刻(小时):每天 0 点与该时刻两个失效点——
# 过了该时刻且数据还不是今天的,即判过期回源。akshare 净值发布集中在 17~22 点,
# 取 22 为保守判定点(发布不确定时宁晚勿空转);只影响回源判定与缓存窗口,不影响写入
NAV_REFRESH_DEADLINE_HOUR = 22


class LogCategory:
    """日志类别(操作日志 / 登录日志)。

    收常量而非入字典:category 是 oper_log_dao 的必过滤条件,且为复合索引
    idx_oper_log_category_time 的首列,改值需重建索引并迁移存量数据。
    字典只能覆盖前端两个 Tab 的文案,动不了查询与索引,收益为负。
    """

    OPERATION = 'operation'
    LOGIN = 'login'
