"""密码工具类：基于 bcrypt 实现密码哈希与校验"""

import bcrypt


class PwdUtil:
    """密码工具类

    提供：
    - get_password_hash: 对明文密码进行 bcrypt 哈希
    - verify_password:   校验明文密码与哈希是否匹配
    """

    @staticmethod
    def get_password_hash(password: str) -> str:
        """对明文密码进行 bcrypt 加密

        :param password: 明文密码
        :return: bcrypt 哈希字符串（含盐与成本因子），形如 $2b$12$...
        """
        # 1. 将明文密码编码为 bytes（bcrypt 要求 bytes 输入）
        password_bytes = password.encode('utf-8')
        # 2. 生成随机盐（默认成本因子 12，迭代 2^12=4096 轮）
        salt = bcrypt.gensalt()
        # 3. 用盐对密码进行哈希
        hashed_bytes = bcrypt.hashpw(password_bytes, salt)
        # 4. 解码为 str 便于存入数据库
        return hashed_bytes.decode('utf-8')

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """校验明文密码与数据库存储的哈希是否一致

        :param plain_password:  用户输入的明文密码
        :param hashed_password: 数据库存储的 bcrypt 哈希
        :return: True 表示密码正确，False 表示错误；若哈希为空返回 False
        """
        # 防御性检查：哈希为空直接返回 False（参考若依实现）
        if not hashed_password:
            return False
        # 将明文与哈希都编码为 bytes
        plain_bytes = plain_password.encode('utf-8')
        hashed_bytes = hashed_password.encode('utf-8')
        # checkpw 会自动从 hashed_bytes 中解析盐与成本因子重新哈希明文并比对
        return bcrypt.checkpw(plain_bytes, hashed_bytes)