"""自定义异常体系

所有业务异常继承 FrameworkException，统一构造签名 (data, message)：
- data: 异常附加数据（如用户名、token 等），可选
- message: 异常消息文本，可选

"""


class FrameworkException(Exception):
    """框架异常基类

    所有自定义异常的根，统一 (data, message) 构造签名。
    不直接继承 Python 内置 BaseException，避免覆盖 SystemExit/KeyboardInterrupt。
    """

    def __init__(self, data: object | None = None, message: str | None = None) -> None:
        self.data = data
        self.message = message
        # 调用父类构造，保证 str(exc) 行为正常
        super().__init__(message)


class LoginException(FrameworkException):
    """登录异常

    场景：用户名密码错误、验证码错误、账号被锁定等登录流程异常。
    处理器映射：code=601（业务失败码），HTTP 200。
    """


class AuthException(FrameworkException):
    """认证/令牌异常

    场景：token 过期、token 无效、token 缺失。
    处理器映射：code=401（未认证），HTTP 200。
    """


class PermissionException(FrameworkException):
    """权限异常

    场景：无接口访问权限、越权访问。
    处理器映射：code=403（禁止访问），HTTP 200。
    """


class ServiceException(FrameworkException):
    """服务异常

    场景：业务逻辑出错（如余额不足、库存不够），需记录 error 日志。
    处理器映射：code=500（系统错误），HTTP 200。
    """


class ServiceWarning(FrameworkException):
    """服务警告

    场景：业务逻辑的软性提示（如「该操作不可逆，请确认」），需记录 warning 日志。
    处理器映射：code=601（业务警告），HTTP 200。
    """


class ModelValidatorException(FrameworkException):
    """模型校验异常

    场景：Pydantic 模型字段校验失败、自定义校验规则不通过。
    处理器映射：code=601（校验失败），HTTP 200。
    """