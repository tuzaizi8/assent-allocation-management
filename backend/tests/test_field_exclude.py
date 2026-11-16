"""字段裁剪(exclude)机制单元测试(2026-08-31 敏感信息泄露修复)。

覆盖三块:
① CamelCaseUtil.transform_result 的 exclude 过滤(含驼峰名容错)
② PageUtil.paginate 两个分支(分页/非分页)的 exclude 透传(FakeDb 驱动,无真实数据库)
③ UserDao.get_user_list 必须携带 exclude={'password'}(防回归锚点)
"""

import pytest
from sqlalchemy import select

from module_system.dao.user_dao import UserDao
from module_system.entity.do.user_do import SysUser
from module_system.entity.vo.user_vo import UserPageQueryModel
from utils.camel_case_util import CamelCaseUtil
from utils.page_util import PageUtil


class TestTransformResultExclude:
    """transform_result 的 exclude 过滤"""

    def make_user(self) -> SysUser:
        return SysUser(
            user_id=2,
            user_name='tester',
            nick_name='测试用户',
            password='$2b$12$secret-hash',
            status='0',
            del_flag='0',
        )

    def test_exclude_removes_sensitive_column(self):
        """exclude={'password'} → 输出无 password,其余字段正常驼峰化"""
        result = CamelCaseUtil.transform_result(self.make_user(), exclude={'password'})
        assert 'password' not in result
        assert result['userName'] == 'tester'
        assert result['userId'] == 2

    def test_exclude_none_keeps_all_fields(self):
        """exclude=None(默认) → 行为与修复前完全一致"""
        result = CamelCaseUtil.transform_result(self.make_user())
        assert 'password' in result
        assert result['password'] == '$2b$12$secret-hash'

    def test_exclude_accepts_camel_case_name(self):
        """容错:调用方误传驼峰名也能命中"""
        result = CamelCaseUtil.transform_result(
            {'login_ip': '127.0.0.1', 'user_name': 'x'}, exclude={'loginIp'}
        )
        assert 'loginIp' not in result
        assert result['userName'] == 'x'

    def test_exclude_on_dict(self):
        """dict 输入同样生效"""
        result = CamelCaseUtil.transform_result(
            {'password': 'p', 'nick_name': 'n'}, exclude={'password'}
        )
        assert result == {'nickName': 'n'}


class _FakeScalars:
    """伪 ScalarResult:.all() 返回标量(非分页分支消费)。"""

    def __init__(self, rows: list):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeResult:
    """伪 CursorResult:同时支撑 count(scalar) 与取行(all) 两种消费。"""

    def __init__(self, rows: list):
        self._rows = rows

    def scalar(self):
        return len(self._rows)

    def all(self):
        return [(row,) for row in self._rows]

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeDb:
    """伪 AsyncSession:execute 恒返回 _FakeResult(两次调用分别是 count 与取行)。"""

    def __init__(self, rows: list):
        self._rows = rows

    async def execute(self, query):
        return _FakeResult(self._rows)


class TestPaginateExclude:
    """PageUtil.paginate 的 exclude 透传(两分支)"""

    def make_rows(self) -> list[SysUser]:
        return [
            SysUser(user_id=i, user_name=f'u{i}', password='$2b$hash', status='0', del_flag='0')
            for i in (1, 2)
        ]

    @pytest.mark.asyncio
    async def test_paged_branch_excludes_password(self):
        """is_page=True 分支:PageModel.rows 无 password"""
        page = await PageUtil.paginate(
            _FakeDb(self.make_rows()), select(SysUser), 1, 10, is_page=True, exclude={'password'}
        )
        assert page.total == 2
        for row in page.rows:
            assert 'password' not in row
            assert 'userName' in row

    @pytest.mark.asyncio
    async def test_unpaged_branch_excludes_password(self):
        """is_page=False 分支:list[dict] 无 password"""
        rows = await PageUtil.paginate(
            _FakeDb(self.make_rows()), select(SysUser), 1, 10, is_page=False, exclude={'password'}
        )
        assert len(rows) == 2
        for row in rows:
            assert 'password' not in row

    @pytest.mark.asyncio
    async def test_default_no_exclude_backward_compatible(self):
        """不传 exclude → 全字段保留(其余 4 个 DAO 调用方行为不变)"""
        page = await PageUtil.paginate(_FakeDb(self.make_rows()), select(SysUser), 1, 10, is_page=True)
        assert all('password' in row for row in page.rows)


class TestUserDaoExcludeWiring:
    """UserDao.get_user_list 必须传 exclude={'password'}(防回归)"""

    @pytest.mark.asyncio
    async def test_get_user_list_passes_exclude(self, monkeypatch):
        recorded: dict = {}

        async def fake_paginate(db, query, page_num, page_size, is_page, exclude=None):
            recorded['exclude'] = exclude
            return []

        monkeypatch.setattr('module_system.dao.user_dao.PageUtil.paginate', fake_paginate)

        await UserDao.get_user_list(None, UserPageQueryModel(), is_page=True)
        assert recorded['exclude'] == {'password'}
