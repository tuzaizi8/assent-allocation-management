"""个人资料自助接口单元测试(资料读/改 + 改密)。

覆盖三块:
① 入参模型约束:只收昵称与手机号、长度口径、新旧密码不得相同
② 改资料只落允许的列(防越权改邮箱/账号/角色的结构性防线,不是"记得别传")
③ 改密:原密码校验失败 → 601;成功 → 新哈希 + 改密时间 + 作废会话;删会话失败不影响改密成功

对齐 tests/test_oper_log.py 的 monkeypatch 风格(不连真库/真 Redis)。
"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from exceptions.exceptions import ServiceWarning
from module_system.entity.vo.auth_vo import PasswordUpdateModel, ProfileUpdateModel
from module_system.service.auth_service import LOGIN_TOKEN_KEY, AuthService


def make_user(**overrides) -> SimpleNamespace:
    """最小可用 SysUser 桩:只带被测代码会读到的属性。"""
    base = {
        'user_id': 7,
        'user_name': 'me@example.com',
        'nick_name': '旧昵称',
        'email': 'me@example.com',
        'phonenumber': '',
        'dept_id': None,
        'status': '0',
        'password': 'old-hash',
        'create_time': datetime(2026, 1, 1),
        'login_date': datetime(2026, 9, 1),
        'pwd_update_date': None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeDb:
    """只关心 commit 次数:被测方法不碰其他会话能力。"""

    def __init__(self) -> None:
        self.committed = 0

    async def commit(self) -> None:
        self.committed += 1


class FakeRedis:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


class TestProfileUpdateModel:
    """入参模型:字段集与长度口径是越权改资料的第一道防线"""

    def test_camel_alias_resolution(self):
        model = ProfileUpdateModel.model_validate({'nickName': '小明', 'phonenumber': '13800000000'})
        assert model.nick_name == '小明'
        assert model.phonenumber == '13800000000'

    def test_nick_name_required_and_bounded(self):
        with pytest.raises(ValidationError):
            ProfileUpdateModel.model_validate({'nickName': ''})
        with pytest.raises(ValidationError):
            ProfileUpdateModel.model_validate({'nickName': 'x' * 31})

    def test_phonenumber_max_length(self):
        with pytest.raises(ValidationError):
            ProfileUpdateModel.model_validate({'nickName': '小明', 'phonenumber': '1' * 12})

    def test_email_etc_not_part_of_model(self):
        """模型里没有 email/user_name/role → 传了也被丢弃,构造不出改这些列的 payload"""
        model = ProfileUpdateModel.model_validate({'nickName': '小明', 'email': 'attacker@x.com'})
        assert not hasattr(model, 'email')


class TestPasswordUpdateModel:
    """入参模型:新旧必须不同 + 最小长度沿用注册口径"""

    def test_new_must_differ_from_old(self):
        with pytest.raises(ValidationError):
            PasswordUpdateModel.model_validate({'oldPassword': 'abc123', 'newPassword': 'abc123'})

    def test_new_password_min_length(self):
        with pytest.raises(ValidationError):
            PasswordUpdateModel.model_validate({'oldPassword': 'abc123', 'newPassword': 'abc'})


class TestUpdateProfileServices:
    @pytest.mark.asyncio
    async def test_writes_only_allowed_columns(self, monkeypatch):
        """只落 user_id/nick_name/phonenumber/审计字段——多一列都算越权"""
        captured: dict = {}
        state = {'nick_name': '旧昵称'}

        async def fake_get_user(db, user_id):
            return make_user(user_id=user_id, nick_name=state['nick_name'])

        async def fake_edit_user(db, payload):
            captured.update(payload)
            state['nick_name'] = payload['nick_name']

        monkeypatch.setattr('module_system.dao.user_dao.UserDao.get_user_by_id', fake_get_user)
        monkeypatch.setattr('module_system.dao.user_dao.UserDao.edit_user_dao', fake_edit_user)
        monkeypatch.setattr(
            'module_system.service.auth_service.get_current_user_or_none',
            lambda: SimpleNamespace(user_name='tester', is_admin=False),
        )

        db = FakeDb()
        result = await AuthService.update_profile_services(
            db,
            {'user_id': 7},
            ProfileUpdateModel(nickName='新昵称', phonenumber='13800000000'),
        )

        assert set(captured) == {'user_id', 'nick_name', 'phonenumber', 'update_by', 'update_time'}
        assert captured['nick_name'] == '新昵称'
        assert captured['phonenumber'] == '13800000000'
        assert captured['update_by'] == 'tester'
        assert db.committed == 1
        # 返回值是"改完再读一次"的最新资料(页面左卡要立刻显示新昵称)
        assert result.nick_name == '新昵称'

    @pytest.mark.asyncio
    async def test_empty_phonenumber_written_as_empty_string(self, monkeypatch):
        """手机号清空写空串而非 None:库列是 server_default='' 的字符串列"""
        captured: dict = {}

        async def fake_get_user(db, user_id):
            return make_user(user_id=user_id)

        async def fake_edit_user(db, payload):
            captured.update(payload)

        monkeypatch.setattr('module_system.dao.user_dao.UserDao.get_user_by_id', fake_get_user)
        monkeypatch.setattr('module_system.dao.user_dao.UserDao.edit_user_dao', fake_edit_user)

        await AuthService.update_profile_services(
            FakeDb(), {'user_id': 7}, ProfileUpdateModel(nickName='小明', phonenumber=None)
        )

        assert captured['phonenumber'] == ''


class TestUpdatePasswordServices:
    @pytest.mark.asyncio
    async def test_wrong_old_password_rejected_without_touching_session(self, monkeypatch):
        async def fake_get_user(db, user_id):
            return make_user(user_id=user_id)

        monkeypatch.setattr('module_system.dao.user_dao.UserDao.get_user_by_id', fake_get_user)
        monkeypatch.setattr('utils.pwd_util.PwdUtil.verify_password', lambda raw, hashed: False)

        redis = FakeRedis()
        with pytest.raises(ServiceWarning):
            await AuthService.update_password_services(
                FakeDb(),
                redis,
                {'user_id': 7},
                PasswordUpdateModel.model_validate({'oldPassword': 'bad123', 'newPassword': 'new12345'}),
            )

        # 原密码不对:不该写库、更不该把当前会话踢掉
        assert redis.deleted == []

    @pytest.mark.asyncio
    async def test_success_updates_hash_and_invalidates_session(self, monkeypatch):
        captured: dict = {}

        async def fake_get_user(db, user_id):
            return make_user(user_id=user_id)

        async def fake_edit_user(db, payload):
            captured.update(payload)

        monkeypatch.setattr('module_system.dao.user_dao.UserDao.get_user_by_id', fake_get_user)
        monkeypatch.setattr('module_system.dao.user_dao.UserDao.edit_user_dao', fake_edit_user)
        monkeypatch.setattr('utils.pwd_util.PwdUtil.verify_password', lambda raw, hashed: raw == 'old123')
        monkeypatch.setattr('utils.pwd_util.PwdUtil.get_password_hash', lambda raw: f'hashed::{raw}')
        monkeypatch.setattr(
            'module_system.service.auth_service.get_current_user_or_none',
            lambda: SimpleNamespace(user_name='tester', is_admin=False),
        )

        db, redis = FakeDb(), FakeRedis()
        await AuthService.update_password_services(
            db,
            redis,
            {'user_id': 7},
            PasswordUpdateModel.model_validate({'oldPassword': 'old123', 'newPassword': 'new12345'}),
        )

        assert captured['password'] == 'hashed::new12345'
        assert isinstance(captured['pwd_update_date'], datetime)
        assert captured['update_by'] == 'tester'
        assert db.committed == 1
        assert redis.deleted == [LOGIN_TOKEN_KEY.format(user_id=7)]

    @pytest.mark.asyncio
    async def test_session_delete_failure_does_not_break_password_change(self, monkeypatch):
        """先落库再删会话:Redis 抖动时密码已改成功,不能让整个请求报失败(否则用户既改不了也登不进)"""

        async def fake_get_user(db, user_id):
            return make_user(user_id=user_id)

        async def fake_edit_user(db, payload):
            return None

        class BoomRedis:
            async def delete(self, key):
                raise RuntimeError('redis down')

        monkeypatch.setattr('module_system.dao.user_dao.UserDao.get_user_by_id', fake_get_user)
        monkeypatch.setattr('module_system.dao.user_dao.UserDao.edit_user_dao', fake_edit_user)
        monkeypatch.setattr('utils.pwd_util.PwdUtil.verify_password', lambda raw, hashed: True)

        db = FakeDb()
        await AuthService.update_password_services(
            db,
            BoomRedis(),
            {'user_id': 7},
            PasswordUpdateModel.model_validate({'oldPassword': 'old123', 'newPassword': 'new12345'}),
        )

        assert db.committed == 1
