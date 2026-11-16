"""通用枚举定义。"""

from enum import Enum


class RedisInitKeyConfig(Enum):
    """系统内置 Redis 键名前缀。

    所有写入 Redis 的业务键都应以这里的 key 作为前缀，
    避免硬编码字符串，同时便于统一排查和清理。
    """

    @property
    def key(self) -> str | None:
        """键名前缀（如 access_token）。"""
        return self.value.get('key')

    @property
    def remark(self) -> str | None:
        """用途说明。"""
        return self.value.get('remark')

    LOGIN_TOKEN = {'key': 'login_tokens', 'remark': '登录会话令牌(单设备登录,新登录覆盖旧值)'}
    SYS_DICT = {'key': 'sys_dict', 'remark': '数据字典'}
    SYS_CONFIG = {'key': 'sys_config', 'remark': '配置信息'}
    API_CACHE = {'key': 'api_cache', 'remark': '接口响应缓存'}
    API_RATE_LIMIT = {'key': 'api_rate_limit', 'remark': '接口限流'}
    CAPTCHA_CODES = {'key': 'captcha_codes', 'remark': '图片验证码'}
    ACCOUNT_LOCK = {'key': 'account_lock', 'remark': '用户锁定'}
    PASSWORD_ERROR_COUNT = {'key': 'password_error_count', 'remark': '密码错误次数'}
    SMS_CODE = {'key': 'sms_code', 'remark': '短信验证码'}
    FUND_NAV = {'key': 'fund_nav', 'remark': '基金复权净值(服务层三级缓存,TTL 1小时)'}
    FUND_NAV_RAW = {'key': 'fund_nav_raw', 'remark': '基金原始净值(服务层三级缓存,TTL 1小时)'}
    MONEY_FUND_YIELD = {'key': 'money_fund_yield', 'remark': '货币基金七日年化序列(服务层缓存,TTL 1小时)'}
    TX_DUP_GUARD = {'key': 'tx_dup_guard', 'remark': '交易写入防重复提交窗口(60s SET NX)'}
    FUND_INFO = {'key': 'fund_info', 'remark': '基金详细信息(同花顺档案,服务层三级缓存,TTL 1小时)'}
    INDEX_NAV = {'key': 'index_nav', 'remark': '指数净值(服务层三级缓存,TTL 6小时)'}
    RISK_FREE_RATE = {'key': 'risk_free_rate', 'remark': '无风险利率(中国国债2年期收益率序列,TTL 6小时)'}