from pydantic_settings import BaseSettings,SettingsConfigDict
from typing import Literal
from pydantic import computed_field
from functools import lru_cache
from urllib.parse import quote_plus

class AppSettings(BaseSettings):
    """应用全局配置"""

    model_config = SettingsConfigDict(env_file='.env.dev',extra='ignore')

    app_env: Literal['dev', 'prod', 'test'] = 'dev'
    app_name: str = 'Assent Allocation Management'
    app_host: str = '0.0.0.0'
    app_port: int = 8000
    app_root_path: str = '/api'
    app_reload: bool = True
    app_workers: int = 1

class DatabaseSettings(BaseSettings):
    """数据库配置"""

    model_config = SettingsConfigDict(env_file='.env.dev', extra='ignore')

    db_type: Literal['mysql', 'postgresql'] = 'postgresql'
    db_host: str = '127.0.0.1'
    db_port: int = 5432
    db_username: str = 'postgres'
    db_password: str = ''
    db_database: str = 'fastapi_scaffold'
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600
    db_pool_timeout: int = 30

    @computed_field
    @property
    def async_url(self) -> str:
        """异步数据库连接 URL（密码做 URL 编码）"""
        password_encoded = quote_plus(self.db_password)
        if self.db_type == 'mysql':
            return (
                f'mysql+asyncmy://{self.db_username}:{password_encoded}'
                f'@{self.db_host}:{self.db_port}/{self.db_database}'
            )
        return (
            f'postgresql+asyncpg://{self.db_username}:{password_encoded}'
            f'@{self.db_host}:{self.db_port}/{self.db_database}'
        )

class RedisSettings(BaseSettings):
    """Redis 配置。"""

    model_config = SettingsConfigDict(env_file='.env.dev', extra='ignore')

    redis_host: str = '127.0.0.1'
    redis_port: int = 6379
    redis_username: str = ''
    redis_password: str = ''
    redis_database: int = 0

class JwtSettings(BaseSettings):
    """JWT 配置"""

    model_config = SettingsConfigDict(env_file='.env.dev', extra='ignore')

    jwt_secret_key: str
    jwt_algorithm: str = 'HS256'
    jwt_expire_minutes: int = 1440

class LogSettings(BaseSettings):
    """日志配置"""

    model_config = SettingsConfigDict(env_file='.env.dev', extra='ignore')

    log_level: str = 'DEBUG'
    log_dir: str = 'logs'
    log_rotation: str = '00:00'
    log_retention: str = '30 days'
    log_compression: str = 'zip'
    log_mask_fields: str = 'password,token,secret,api_key,jwt,authorization'
    log_partial_mask_fields: str = 'phone,email,id_card'

    @computed_field
    @property
    def mask_fields_list(self) -> list[str]:
        """完整脱敏字段列表"""
        return [f.strip() for f in self.log_mask_fields.split(',') if f.strip()]

    @computed_field
    @property
    def partial_mask_fields_list(self) -> list[str]:
        """部分脱敏字段列表"""
        return [f.strip() for f in self.log_partial_mask_fields.split(',') if f.strip()]

@lru_cache
def get_app_config() -> AppSettings:
    """获取应用配置（单例）"""
    return AppSettings()

@lru_cache
def get_db_config() -> DatabaseSettings:
    """获取数据库配置（单例）"""
    return DatabaseSettings()

@lru_cache
def get_redis_config() -> RedisSettings:
    """获取 Redis 配置（单例）。"""
    return RedisSettings()

@lru_cache
def get_jwt_config() -> JwtSettings:
    """获取 JWT 配置（单例）"""
    return JwtSettings()

@lru_cache
def get_log_config() -> LogSettings:
    """获取日志配置（单例）"""
    return LogSettings()

# 全局单例（其他模块直接 import 使用）
AppConfig = get_app_config()
DataBaseConfig = get_db_config()
RedisConfig = get_redis_config()
JwtConfig = get_jwt_config()
LogConfig = get_log_config()