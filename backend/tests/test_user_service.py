"""用户-角色分配 service 层单元测试(2026-08-27 用户管理补齐项)。

对齐 test_security.py 的 monkeypatch 风格:fake db(异步 commit/rollback)+
monkeypatch UserDao/唯一性校验,验证 sys_user_role 的写入契约:
新增直插 / 编辑全量替换 / 超管保留 admin 角色保护 / 详情 roleIds 回显。
"""

import pytest

from exceptions.exceptions import ServiceWarning
from module_system.dao.user_dao import UserDao
from module_system.entity.do.user_do import SysUser
from module_system.entity.vo.user_vo import UserAddModel, UserEditModel
from module_system.service.user_service import UserService


class FakeDb:
    """fake AsyncSession:只提供 commit/rollback 计数,供 Service 事务控制。"""

    def __init__(self):
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1


class CallRecorder:
    """记录 DAO 调用参数的桩。"""

    def __init__(self):
        self.calls = []

    async def __call__(self, db, *args):
        self.calls.append(args)
        return None


def make_user(user_id: int, user_name: str = 'tester') -> SysUser:
    """构造真实 SysUser DO 实例(CamelCaseUtil.transform_result 走 __table__.columns 路径)。"""
    return SysUser(
        user_id=user_id,
        user_name=user_name,
        nick_name='测试用户',
        password='secret',
        status='0',
        del_flag='0',
    )


@pytest.fixture
def unique_ok(monkeypatch):
    """用户名唯一性校验恒通过。"""

    async def fake_check(query_db, page_object):
        return True

    monkeypatch.setattr(UserService, 'check_user_name_unique_services', fake_check)


class TestAddUserWithRoleIds:
    """新增用户绑定角色"""

    @pytest.mark.asyncio
    async def test_add_user_binds_roles(self, monkeypatch, unique_ok):
        """带 roleIds 新增 → batch_add_user_role_dao 收到 (flush 后的 user_id, roleIds)"""
        db = FakeDb()
        batch = CallRecorder()

        async def fake_add_user_dao(query_db, add_user):
            add_user.user_id = 99  # 模拟 flush 回填自增主键
            return add_user

        monkeypatch.setattr(UserDao, 'add_user_dao', fake_add_user_dao)
        monkeypatch.setattr(UserDao, 'batch_add_user_role_dao', batch)

        page_object = UserAddModel(
            userName='tester', nickName='测试用户', password='123456', status='0', roleIds=[2]
        )
        result = await UserService.add_user_services(db, page_object)

        assert result.is_success is True
        assert batch.calls == [(99, [2])]
        assert db.commit_count == 1
        assert db.rollback_count == 0

    @pytest.mark.asyncio
    async def test_add_user_without_role_ids_skips_binding(self, monkeypatch, unique_ok):
        """roleIds 缺省(空) → 不触发关联插入"""
        db = FakeDb()
        batch = CallRecorder()

        async def fake_add_user_dao(query_db, add_user):
            add_user.user_id = 100
            return add_user

        monkeypatch.setattr(UserDao, 'add_user_dao', fake_add_user_dao)
        monkeypatch.setattr(UserDao, 'batch_add_user_role_dao', batch)

        page_object = UserAddModel(userName='tester2', nickName='测试', password='123456', status='0')
        result = await UserService.add_user_services(db, page_object)

        assert result.is_success is True
        assert batch.calls == []
        assert db.commit_count == 1


class TestSingleRoleConstraint:
    """全局单选约束(需求修订 2026-08-27):至多一个角色"""

    @pytest.mark.asyncio
    async def test_add_user_multiple_roles_rejected(self, monkeypatch, unique_ok):
        """新增传 roleIds=[1,2] → ServiceWarning,零写入零提交"""
        db = FakeDb()
        batch = CallRecorder()

        async def fake_add_user_dao(query_db, add_user):
            add_user.user_id = 101
            return add_user

        monkeypatch.setattr(UserDao, 'add_user_dao', fake_add_user_dao)
        monkeypatch.setattr(UserDao, 'batch_add_user_role_dao', batch)

        page_object = UserAddModel(
            userName='multi', nickName='多角色', password='123456', status='0', roleIds=[1, 2]
        )
        with pytest.raises(ServiceWarning) as exc_info:
            await UserService.add_user_services(db, page_object)
        assert '一个用户只能绑定一个角色' in str(exc_info.value)
        assert batch.calls == []
        assert db.commit_count == 0

    @pytest.mark.asyncio
    async def test_edit_user_multiple_roles_rejected(self, monkeypatch, unique_ok):
        """编辑传 roleIds=[2,3] → ServiceWarning,零写入零提交"""
        db = FakeDb()
        batch = CallRecorder()

        async def fake_get_user_by_id(query_db, user_id):
            return make_user(user_id=6)

        async def fake_get_user_role_ids(query_db, user_id):
            return [2]

        monkeypatch.setattr(UserDao, 'get_user_by_id', fake_get_user_by_id)
        monkeypatch.setattr(UserDao, 'get_user_role_ids', fake_get_user_role_ids)
        monkeypatch.setattr(UserDao, 'batch_add_user_role_dao', batch)

        page_object = UserEditModel(
            userId=6, userName='tester6', nickName='测试', status='0', roleIds=[2, 3]
        )
        with pytest.raises(ServiceWarning) as exc_info:
            await UserService.edit_user_services(db, page_object)
        assert '一个用户只能绑定一个角色' in str(exc_info.value)
        assert batch.calls == []
        assert db.commit_count == 0


class TestEditUserFullReplacement:
    """编辑用户角色全量替换"""

    @pytest.mark.asyncio
    async def test_edit_user_replaces_roles_and_pops_keys(self, monkeypatch, unique_ok):
        """带 roleIds 编辑 → 先删后插;且 edit_user_dao 收到的 dict 不含 role_ids/role 键"""
        db = FakeDb()
        delete_calls = CallRecorder()
        batch = CallRecorder()
        edit_dao = CallRecorder()

        async def fake_get_user_by_id(query_db, user_id):
            return make_user(user_id=5)

        async def fake_get_user_role_ids(query_db, user_id):
            return [1, 2]  # 旧绑定:1、2

        monkeypatch.setattr(UserDao, 'get_user_by_id', fake_get_user_by_id)
        monkeypatch.setattr(UserDao, 'get_user_role_ids', fake_get_user_role_ids)
        monkeypatch.setattr(UserDao, 'edit_user_dao', edit_dao)
        monkeypatch.setattr(UserDao, 'delete_user_role_by_user_ids', delete_calls)
        monkeypatch.setattr(UserDao, 'batch_add_user_role_dao', batch)

        page_object = UserEditModel(
            userId=5, userName='tester', nickName='新昵称', status='0', roleIds=[3]
        )
        result = await UserService.edit_user_services(db, page_object)

        assert result.is_success is True
        # 全量替换:先删旧绑定(user_id 列表),再插所选角色(单选语义:单元素)
        assert delete_calls.calls == [([5],)]
        assert batch.calls == [(5, [3])]
        # 用户表更新 dict 已剔除关联字段(防 update(SysUser) 未知列报错)
        for edit_dict in [c[0] for c in edit_dao.calls]:
            assert 'role_ids' not in edit_dict
            assert 'role' not in edit_dict
            assert edit_dict.get('user_id') == 5
        assert db.commit_count == 1
        assert db.rollback_count == 0

    @pytest.mark.asyncio
    async def test_edit_admin_requires_admin_role(self, monkeypatch, unique_ok):
        """超管保护:user_id=1 提交 roleIds 不含 admin(role_id=1) → ServiceWarning(601)"""
        db = FakeDb()
        batch = CallRecorder()

        async def fake_get_user_by_id(query_db, user_id):
            return make_user(user_id=1, user_name='admin')

        async def fake_get_user_role_ids(query_db, user_id):
            return [1]

        monkeypatch.setattr(UserDao, 'get_user_by_id', fake_get_user_by_id)
        monkeypatch.setattr(UserDao, 'get_user_role_ids', fake_get_user_role_ids)
        monkeypatch.setattr(UserDao, 'batch_add_user_role_dao', batch)

        page_object = UserEditModel(
            userId=1, userName='admin', nickName='管理员', status='0', roleIds=[2]
        )
        with pytest.raises(ServiceWarning):
            await UserService.edit_user_services(db, page_object)
        # 保护命中于动库前:零写入、零提交
        assert batch.calls == []
        assert db.commit_count == 0


class TestUserDetailRoleIds:
    """用户详情 roleIds 回显"""

    @pytest.mark.asyncio
    async def test_detail_returns_role_ids_and_no_password(self, monkeypatch):
        """详情返回驼峰 dict:含 roleIds,不含 password"""
        db = FakeDb()

        async def fake_get_user_by_id(query_db, user_id):
            return make_user(user_id=5, user_name='tester')

        async def fake_get_user_role_ids(query_db, user_id):
            return [1, 2]

        monkeypatch.setattr(UserDao, 'get_user_by_id', fake_get_user_by_id)
        monkeypatch.setattr(UserDao, 'get_user_role_ids', fake_get_user_role_ids)

        result = await UserService.user_detail_services(db, 5)

        assert result['roleIds'] == [1, 2]
        assert 'password' not in result
        assert result['userName'] == 'tester'
