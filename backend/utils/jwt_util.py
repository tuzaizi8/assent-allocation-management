"""JWT 工具类：基于 PyJWT 实现令牌生成与解码"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from config.settings import JwtConfig


class JwtUtil:
    """JWT 工具类

    提供：
    - create_access_token: 生成 JWT 令牌
    - decode_token:        解码并验证 JWT 令牌
    """

    @staticmethod
    def create_access_token(
        data: dict[str, Any],
        expires_delta: timedelta | None = None,
    ) -> str:
        """生成 JWT 访问令牌

        :param data: 需要写入 payload 的业务数据（如 user_id、username）
        :param expires_delta: 自定义过期时长；为 None 时使用配置默认值
        :return: 编码后的 JWT 字符串
        """
        # 1. 拷贝传入数据，避免污染调用方字典
        to_encode = data.copy()
        # 2. 计算过期时间（统一使用 UTC，避免时区问题）
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                minutes=JwtConfig.jwt_expire_minutes
            )
        # 3. 将 exp 写入 payload（PyJWT 会自动校验 exp 是否过期）
        to_encode.update({'exp': expire})
        # 4. 用密钥和算法签名生成 JWT
        encoded_jwt = jwt.encode(
            to_encode,
            JwtConfig.jwt_secret_key,
            algorithm=JwtConfig.jwt_algorithm,
        )
        return encoded_jwt

    @staticmethod
    def decode_token(token: str) -> dict[str, Any]:
        """解码并验证 JWT 令牌

        :param token: JWT 字符串（支持带或不带 'Bearer ' 前缀）
        :return: payload 字典
        :raises InvalidTokenError: 令牌无效或已过期
        """
        # 1. 兼容前端可能传入的 'Bearer xxx' 格式
        if token.startswith('Bearer '):
            token = token.split(' ', 1)[1]
        # 2. 解码并验证签名 + exp
        payload = jwt.decode(
            token,
            JwtConfig.jwt_secret_key,
            algorithms=[JwtConfig.jwt_algorithm],
        )
        return payload