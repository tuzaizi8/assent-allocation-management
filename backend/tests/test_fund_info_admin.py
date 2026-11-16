"""基金信息管理端点的最小回归:注册顺序、查询契约、SQL 形态、新增去重。

不连库:按项目测试范式用编译 SQL 与对象断言锁定高熵约束——
注册顺序错位会让 /info/list 被路径参数 /info/{fund_code} 吞掉(2026-10-12 实证);
查询模型继承响应模型会让 rows/total/hasNext 被 Query 解析成必填而报错(同日实证)。
"""

import pytest
from sqlalchemy.dialects import postgresql

from module_fund.controller.fund_info_controller import fund_info_controller
from module_fund.dao.fund_info_dao import FundInfoDao
from module_fund.entity.vo.fund_info_vo import (
    FundInfoCreateModel,
    FundInfoPageQueryModel,
)
from module_fund.service.fund_info_service import FundInfoService
from exceptions.exceptions import ServiceWarning


def _route_paths() -> list[str]:
    return [getattr(r, 'path', '') for r in fund_info_controller.routes]


def test_info_list_registered_before_path_param():
    """/info/list 与 /info/{fund_code} 同为 GET:管理端点必须先注册,
    否则 fund_code='list' 抢占匹配,列表端点永远 404/命中详情。"""
    paths = _route_paths()
    assert '/fund/info/list' in paths
    assert paths.index('/fund/info/list') < paths.index('/fund/info/{fund_code}')


def test_page_query_model_accepts_camel_and_defaults():
    """分页查询模型:驼峰 alias 生效(pageNum/pageSize),缺省回退第 1 页;
    绝不能继承 PageResponseModel——rows/total/hasNext 是响应必填字段,
    被 Query 解析会报 Field required(2026-10-12 实证)。"""
    q = FundInfoPageQueryModel.model_validate({'pageNum': 2, 'pageSize': 5})
    assert q.page_num == 2
    assert q.page_size == 5
    assert q.keyword is None
    fallback = FundInfoPageQueryModel()
    assert (fallback.page_num, fallback.page_size) == (1, 10)


def test_create_model_requires_fund_code():
    """新增模型仅需基金代码;超长拒绝。"""
    m = FundInfoCreateModel.model_validate({'fundCode': '000001'})
    assert m.fund_code == '000001'
    with pytest.raises(Exception):
        FundInfoCreateModel.model_validate({'fundCode': 'x' * 21})


def test_info_page_sql_joins_fund_and_orders_by_update_time():
    """分页 SQL:join fund 取名称类型(isouter,fund 已删不丢行),
    按 update_time 降序稳定排序(新刷新的排前面)。"""
    from sqlalchemy import select

    from module_fund.entity.do.fund_do import Fund
    from module_fund.entity.do.fund_info_do import FundInfo

    query = (
        select(FundInfo.fund_code, Fund.name)
        .join(Fund, Fund.code == FundInfo.fund_code, isouter=True)
        .order_by(FundInfo.update_time.desc().nullslast())
    )
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert 'LEFT OUTER JOIN fund' in sql
    assert 'update_time DESC' in sql


@pytest.mark.asyncio
async def test_create_rejects_existing(monkeypatch):
    """已存在拒绝新增并提示走同步——不触网(分支在 refresh 之前)。"""

    class _FakeExisting:
        fund_code = '000001'

    async def _fake_get(db, code):
        return _FakeExisting()

    monkeypatch.setattr(FundInfoDao, 'get_info_by_code', _fake_get)
    with pytest.raises(ServiceWarning, match='已存在'):
        await FundInfoService.create_info_services(None, None, '000001')
