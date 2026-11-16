"""交易导入 Excel 模板契约测试:模板表头与解析器同源,且模板数据集真能被解析出来。

模板是给用户填写的唯一规范入口,这里锁四层:
① 表头逐字与既定 8 列一致;
② 表头能被兜底适配器(generic)映射回全部字段 —— 改了别名却忘了改模板,这条会响;
③ 说明行写在表头之上,而 _locate_header 是全表取最优行,必须仍选中真表头;
④ 模板原样走「读取 → 选适配器 → 抽记录」应解析出示例两行(1 买 1 赎)。
"""

import io
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook
from starlette.requests import Request

from module_portfolio.service.excel_service import (
    TEMPLATE_FIELDS,
    TEMPLATE_HEADER_ROW,
    ExcelService,
)
from module_portfolio.service.statement_adapters import (
    ADAPTERS,
    DEFAULT_ADAPTER_KEY,
    _locate_header,
    _map_columns,
    detect_adapter,
    extract_records,
)
from module_portfolio.controller.import_controller import download_import_template
from module_portfolio.service.statement_readers import MIME_XLSX, read_document

EXPECTED_HEADERS = (
    '确认日期', '基金代码', '基金名称', '交易类型', '确认份额', '确认净值', '确认金额', '手续费',
)


def _template_bytes() -> bytes:
    return ExcelService._import_template_sync()


def _template_sheet():
    return load_workbook(io.BytesIO(_template_bytes())).active


def _column(name: str) -> int:
    """表头名 → 1 起的列号(openpyxl 口径)。"""
    return EXPECTED_HEADERS.index(name) + 1


def test_template_headers_are_the_nine_semantic_columns():
    """表头逐字一致,且与 generic 适配器的首个别名同源。"""
    ws = _template_sheet()
    headers = tuple(
        ws.cell(row=TEMPLATE_HEADER_ROW, column=i + 1).value for i in range(len(TEMPLATE_FIELDS))
    )
    assert headers == EXPECTED_HEADERS
    assert ExcelService._template_headers() == list(EXPECTED_HEADERS)


def test_template_headers_map_back_to_fields():
    """契约锁:模板表头能被兜底适配器映射回全部字段(模板与解析器同源)。"""
    columns = _map_columns(EXPECTED_HEADERS, ADAPTERS[DEFAULT_ADAPTER_KEY])
    assert set(columns) == set(TEMPLATE_FIELDS)
    assert columns['fundCode'] == _column('基金代码') - 1


def test_template_notes_do_not_steal_header_row():
    """说明行在表头之上;全表取最优行的 _locate_header 必须仍选中真表头。"""
    document = read_document(_template_bytes(), 'import-template.xlsx')
    table = document.tables[0]
    header_row, columns = _locate_header(table, ADAPTERS[DEFAULT_ADAPTER_KEY])
    assert header_row is not None
    assert table.rows[header_row][0] == EXPECTED_HEADERS[0]
    assert len(columns) == len(EXPECTED_HEADERS)


def test_template_sample_rows_parse_end_to_end():
    """端到端:模板原样走 读取 → 选适配器 → 抽记录,示例两行应解析成 1 买 1 赎。"""
    document = read_document(_template_bytes(), 'import-template.xlsx')
    adapter = detect_adapter(document)
    assert adapter.key == DEFAULT_ADAPTER_KEY
    records = extract_records(document, adapter)
    assert len(records) == 2
    buy, sell = records
    assert (buy['type'], sell['type']) == ('purchase', 'redemption')
    assert buy['fund_code'] == '005827'
    assert buy['date'] == '2026-01-05'
    assert buy['shares'] == pytest.approx(1000.0)
    assert buy['unit_price'] == pytest.approx(1.2345)
    assert buy['amount'] == pytest.approx(1234.50)
    assert sell['date'] == '2026-06-18'
    assert sell['fund_code'] == '005827'
    assert sell['shares'] == pytest.approx(200.0)


def test_template_text_columns_keep_leading_zeros():
    """基金代码/确认日期两列是文本格式,示例代码不丢前导 0(校验要求 6 位数字)。"""
    ws = _template_sheet()
    for name in ('确认日期', '基金代码'):
        column = _column(name)
        assert ws.cell(row=TEMPLATE_HEADER_ROW, column=column).number_format == '@'
        assert ws.cell(row=TEMPLATE_HEADER_ROW + 1, column=column).number_format == '@'
    assert ws.cell(row=TEMPLATE_HEADER_ROW + 1, column=_column('基金代码')).value == '005827'


@pytest.mark.asyncio
async def test_template_endpoint_returns_xlsx_stream():
    """端到端:调被 @Log 装饰的端点本体(构造最小 Request),断言回 xlsx 文件流。

    service 层测试绕开了装饰器与路由,这条把「@Log 能从实参里拿到 Request」也纳入回归
    —— 漏写 request 形参时它会直接 500(另见 test_oper_log.py 的静态守卫)。
    """
    scope = {
        'type': 'http',
        'method': 'GET',
        'path': '/portfolio/import/transactions/template',
        'scheme': 'http',
        'server': ('localhost', 8000),
        'headers': [],
        'query_string': b'',
        'path_params': {},
    }
    response = await download_import_template(
        request=Request(scope), current_user=SimpleNamespace(user_id=1)
    )

    assert response.media_type == MIME_XLSX
    assert 'attachment' in response.headers['content-disposition']
    body = b''.join([chunk async for chunk in response.body_iterator])
    # xlsx 是 zip 容器:首两字节必是 PK,顺带证明 service 真产出了文件
    assert body[:2] == b'PK'
    assert len(body) > 1000
