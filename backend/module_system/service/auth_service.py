"""认证模块 Service（业务逻辑层）。

职责：登录认证（查库 + bcrypt + 状态检查）、JWT 签发、Redis 会话管理、
SysUser → 前端 User 映射、注册。对接契约见知识库《03-认证对接全链路》。
"""

from datetime import datetime

from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from common.constants import ADMIN_ROLE_KEY, LOGIN_TOKEN_KEY
from config.settings import JwtConfig
from core.context_utils import get_current_user_or_none
from exceptions.exceptions import AuthException, LoginException, ServiceWarning
from module_system.dao.user_dao import UserDao
from module_system.dao.menu_dao import MenuDao
from module_system.entity.do.user_do import SysUser
from module_system.entity.vo.auth_vo import (
    AuthUserModel,
    LoginModel,
    PasswordUpdateModel,
    ProfileModel,
    ProfileUpdateModel,
    RegisterModel,
)
from utils.jwt_util import JwtUtil
from utils.pwd_util import PwdUtil
from utils.log import logger

from fastapi import Request
from utils.client_ip_util import ClientIPUtil

# 会话键 LOGIN_TOKEN_KEY 已收到 common.constants(鉴权依赖 core/security 也要用);
# 单设备登录语义——新登录覆盖旧 token,旧端下次请求会话不匹配 → 401 挤下线


class AuthService:
    """认证模块服务层。"""

    # ---------- 映射 ----------

    @classmethod
    async def build_auth_user(cls, db: AsyncSession, user: SysUser) -> AuthUserModel:
        """SysUser DO → 前端 User 结构映射(permissions 查表装配,契约见 04/05)。

        admin 判定:查 sys_user_role(角色 role_key 含 admin),不再 user_id==1。
        """
        role_keys = await MenuDao.get_user_role_keys(db, user.user_id)
        is_admin = ADMIN_ROLE_KEY in role_keys
        if is_admin:
            permissions = ['*:*:*']
        else:
            permissions = await MenuDao.get_perms_by_user_id(db, user.user_id)
        return AuthUserModel(
            id=str(user.user_id),
            email=user.email,
            first_name=user.nick_name or '',
            last_name='',
            role='ADMIN' if is_admin else 'USER',
            permissions=permissions,
        )

    # ---------- 登录 ----------

    @classmethod
    async def authenticate_user_services(
        cls, db: AsyncSession, login_model: LoginModel
    ) -> SysUser:
        """登录认证：查库 + bcrypt 校验 + 状态检查。

        账号不存在与密码错误返回同一文案（防账号枚举）。
        :raises LoginException: 认证失败（处理器映射 code 601, HTTP 200）
        """
        user = await UserDao.get_user_by_email(db, login_model.email)
        # 统一文案：不区分「邮箱未注册」与「密码错误」
        if not user:
            logger.warning(f"[登录] 认证失败-邮箱未注册 email={login_model.email}")
            raise LoginException(message="用户名或密码错误")
        if not PwdUtil.verify_password(login_model.password, user.password or ""):
            logger.warning(f"[登录] 认证失败-密码错误 user_id={user.user_id}")
            raise LoginException(message="用户名或密码错误")
        if user.status == "1":
            logger.warning(f"[登录] 认证失败-账号已停用 user_id={user.user_id}")
            raise LoginException(message="账号已停用")
        return user

    @classmethod
    async def login_services(
        cls, db: AsyncSession, redis: aioredis.Redis, login_model: LoginModel,request: Request
    ) -> dict:
        """登录：认证 → 签发 JWT → 写 Redis 会话。

        :return: {'jwt': token, 'user': {...前端 User 结构}}
        """
        user = await cls.authenticate_user_services(db, login_model)
        logger.info(f"[登录] 认证通过 user_id={user.user_id}, 开始签发 JWT")
        # 登录日志 operName 回填(9.8 ⑩):@Log 在鉴权前记录,operName 恒为 anonymous——
        # 登录成功后经 request.state 传递实际用户名,由 @Log wrapper 落库前覆写
        # (失败路径不回填:尝试的账号可能不存在,保持 anonymous 语义正确)
        request.state.log_oper_name = user.user_name
        # B5:更新最后登录审计字段
        user.login_ip = ClientIPUtil.get_client_ip(request)
        user.login_date = datetime.now()
        # JWT payload 最小化：只放身份标识（权限不放 token，变更需即时生效）
        token = JwtUtil.create_access_token(data={"user_id": user.user_id, "user_name": user.user_name})
        await redis.set(
            LOGIN_TOKEN_KEY.format(user_id=user.user_id),
            token,
            ex=JwtConfig.jwt_expire_minutes * 60,
        )
        logger.info(
            f"[登录] 会话已写入 Redis key={LOGIN_TOKEN_KEY.format(user_id=user.user_id)} "
            f"TTL={JwtConfig.jwt_expire_minutes * 60}s"
        )
        # 防御范式(同 [[09-高级特性对接]] 12.8):全部 ORM 属性读取在 commit 前完成
        auth_user = await cls.build_auth_user(db, user)
        await db.commit()  # B5:审计字段落库(登录路径此前只读不写,首次引入 commit)
        return {"jwt": token, "user": auth_user.model_dump(by_alias=True)}

    # ---------- 当前用户 ----------

    @classmethod
    async def get_current_user_services(
        cls,
        db: AsyncSession,
        redis: aioredis.Redis,
        payload: dict,
        token: str,
    ) -> AuthUserModel:
        """解析当前登录用户：Redis 会话校验 → 查库 → 映射。

        :param payload: core.security.get_current_user 解码出的 JWT payload（含 user_id）
        :param token: 原始 JWT（oauth2_scheme 提取，无 Bearer 前缀）
        :raises AuthException: 会话失效（登出/挤下线/Redis 重启）或用户不存在（→ 401）
        """
        user_id = payload.get("user_id")
        # Redis 会话校验：不一致 = 已登出 / 被挤下线 / Redis 被清
        if await redis.get(LOGIN_TOKEN_KEY.format(user_id=user_id)) != token:
            logger.warning(f"[鉴权] Redis 会话不匹配 user_id={user_id}（已登出/挤下线/Redis被清）")
            raise AuthException(message="登录状态已失效，请重新登录")
        user = await UserDao.get_user_by_id(db, user_id)
        if not user:
            logger.warning(f"[鉴权] 用户不存在或已被删除 user_id={user_id}")
            raise AuthException(message="用户不存在或已被删除")
        return await cls.build_auth_user(db, user)
    # ---------- 登出 ----------

    @classmethod
    async def logout_services(cls, redis: aioredis.Redis, token: str | None) -> None:
        """登出：删除 Redis 会话（幂等——token 缺失/无效也视为成功）。

        前端登出时序是「先清 localStorage 再发请求」，因此本接口不做强制鉴权。
        """
        if not token:
            return
        try:
            payload = JwtUtil.decode_token(token)
            user_id = payload.get('user_id')
            if user_id is not None:
                logger.info(f"[登出] 删除 Redis 会话 user_id={user_id}")
                await redis.delete(LOGIN_TOKEN_KEY.format(user_id=user_id))
        except Exception as e:
            # 无效 token 的登出同样视为成功(幂等),但记录痕迹
            logger.debug(f"[登出] token 无效,按幂等成功处理 | {e}")
            return

    # ---------- 个人资料(自助) ----------

    @classmethod
    async def get_profile_services(cls, db: AsyncSession, current_user: dict) -> ProfileModel:
        """读取当前登录者资料(可编辑区 + 只读区)。

        :param current_user: get_current_user 返回的 JWT payload(含 user_id);
            角色取请求上下文里的 is_admin——与 /auth/me 同源判定(角色 role_key 含 admin)
        """
        user_id = current_user.get('user_id')
        user = await UserDao.get_user_by_id(db, user_id)
        if not user:
            logger.warning(f'[个人资料] 用户不存在或已被删除 user_id={user_id}')
            raise AuthException(message='用户不存在或已被删除')
        context = get_current_user_or_none()
        return ProfileModel(
            user_name=user.user_name,
            nick_name=user.nick_name,
            email=user.email,
            phonenumber=user.phonenumber,
            role='ADMIN' if context and context.is_admin else 'USER',
            create_time=user.create_time,
            login_date=user.login_date,
            pwd_update_date=user.pwd_update_date,
        )

    @classmethod
    async def update_profile_services(
        cls, db: AsyncSession, current_user: dict, profile_model: ProfileUpdateModel
    ) -> ProfileModel:
        """自助修改昵称与手机号(邮箱/账号/角色不可改——参数里根本不存在这些键)。"""
        user_id = current_user.get('user_id')
        user = await UserDao.get_user_by_id(db, user_id)
        if not user:
            logger.warning(f'[个人资料] 用户不存在或已被删除 user_id={user_id}')
            raise AuthException(message='用户不存在或已被删除')

        context = get_current_user_or_none()
        payload = {
            'user_id': user_id,
            'nick_name': profile_model.nick_name,
            # 空串而非 None:库里该列为 server_default='' 的字符串列,写 None 会让前端拿到 null
            'phonenumber': profile_model.phonenumber or '',
            'update_by': context.user_name if context else user.user_name,
            'update_time': datetime.now(),
        }
        await UserDao.edit_user_dao(db, payload)
        await db.commit()
        logger.info(f'[个人资料] 资料已更新 user_id={user_id}')
        return await cls.get_profile_services(db, current_user)

    @classmethod
    async def update_password_services(
        cls, db: AsyncSession, redis: aioredis.Redis, current_user: dict, password_model: PasswordUpdateModel
    ) -> None:
        """自助修改密码:校验原密码 → 更新哈希 → 作废会话(强制重新登录)。

        :raises ServiceWarning: 原密码不正确(→ 601)
        """
        user_id = current_user.get('user_id')
        user = await UserDao.get_user_by_id(db, user_id)
        if not user:
            logger.warning(f'[个人资料] 用户不存在或已被删除 user_id={user_id}')
            raise AuthException(message='用户不存在或已被删除')

        if not PwdUtil.verify_password(password_model.old_password, user.password or ''):
            logger.warning(f'[个人资料] 原密码校验失败 user_id={user_id}')
            raise ServiceWarning(message='原密码不正确')

        context = get_current_user_or_none()
        password = {
            'user_id': user_id,
            'password': PwdUtil.get_password_hash(password_model.new_password),
            'pwd_update_date': datetime.now(),
            'update_by': context.user_name if context else user.user_name,
            'update_time': datetime.now(),
        }
        await UserDao.edit_user_dao(db, password)
        await db.commit()

        # 先落库再作废会话:删会话失败不能把"密码已改成功"报成失败,否则用户既改不了也登不进
        try:
            await redis.delete(LOGIN_TOKEN_KEY.format(user_id=user_id))
        except Exception as exc:
            logger.warning(f'[个人资料] 会话作废失败(密码已更新) user_id={user_id} | {exc}')
        logger.info(f'[个人资料] 密码已更新并作废会话 user_id={user_id}')

    # ---------- 注册 ----------

    @classmethod
    async def register_services(
        cls, db: AsyncSession, redis: aioredis.Redis, register_model: RegisterModel
    ) -> dict:
        """注册：邮箱唯一校验 → bcrypt 加密 → 落库 → 注册即登录。

        :raises ServiceWarning: 邮箱已注册（→ code 601）
        """
        existing = await UserDao.get_user_by_email(db, register_model.email)
        if existing:
            logger.warning(f"[注册] 邮箱已注册 email={register_model.email}")
            raise ServiceWarning(message="该邮箱已注册")
        user = SysUser(
            # 登录账号暂用邮箱（user_name 非空约束；无独立用户名注册入口）
            user_name=register_model.email,
            nick_name=register_model.nick_name,
            email=register_model.email,
            password=PwdUtil.get_password_hash(register_model.password),
            pwd_update_date=datetime.now(),  # ← B5 新增
            status="0",
            del_flag="0",
            create_by="register",
            create_time=datetime.now(),
        )
        try:
            db.add(user)
            # flush 回填自增主键；会话工厂为 expire_on_commit=False，commit 不会使属性失效，
            # 但主键与属性统一在 commit 前取出，避免返回 dict/实体依赖提交后的会话状态
            await db.flush()
            auth_user = await cls.build_auth_user(db, user)
            user_id, user_name = user.user_id, user.user_name
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        # 注册即登录：与 login_services 相同的签发 + 会话逻辑
        token = JwtUtil.create_access_token(data={'user_id': user_id, 'user_name': user_name})
        await redis.set(
            LOGIN_TOKEN_KEY.format(user_id=user_id),
            token,
            ex=JwtConfig.jwt_expire_minutes * 60,
        )
        logger.info(f'[注册] 注册成功并自动登录 user_id={user_id}')  # commit 后读 ORM 属性会 MissingGreenlet,用 commit 前的局部变量
        return {'jwt': token, 'user': auth_user.model_dump(by_alias=True)}
