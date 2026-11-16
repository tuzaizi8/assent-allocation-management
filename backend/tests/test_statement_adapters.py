"""平台适配配置加载、选择与字段抽取单测。

核心契约:
① 坏 YAML / 缺字段 / 写错字段名 → 启动即报错(含文件名与字段名);
② 抽取不依赖列号(表头挪位、改列序不改代码);
③ 新增平台只加一份 YAML(不碰 py);
④ 平台指纹零命中回落 generic。
"""

import pytest

from exceptions.exceptions import ServiceWarning
from module_portfolio.service.statement_adapters import (
    ADAPTERS,
    _parse_date,
    detect_adapter,
    extract_records,
    load_adapters,
)
from module_portfolio.service.statement_readers import (
    KIND_EXCEL,
    LAYER_TEXT,
    MIME_XLSX,
    DocumentContent,
    DocumentPage,
    DocumentTable,
)
from module_portfolio.service.statement_validators import validate_records

ALIPAY_HEADER = ('确认份额', '基金代码', '申请份额', '订单号', '确认金额', '基金名称', '手续费', '确认日期')


def make_table_document(rows: tuple[tuple[str, ...], ...], lines: tuple[str, ...] = ()) -> DocumentContent:
    """用现成的行列数据造一份文档(不经过 reader,专测适配器)。"""
    table = DocumentTable(page_no=1, rows=rows, row_refs=tuple(range(1, len(rows) + 1)), layer=LAYER_TEXT)
    page = DocumentPage(page_no=1, lines=lines or tuple(' '.join(row) for row in rows), tables=(table,), layer=LAYER_TEXT)
    return DocumentContent(kind=KIND_EXCEL, mime=MIME_XLSX, pages=(page,))


def make_line_document(lines: tuple[str, ...]) -> DocumentContent:
    """只有文本行、没有表格的文档(labelValue 模式用)。"""
    page = DocumentPage(page_no=1, lines=lines, layer=LAYER_TEXT)
    return DocumentContent(kind=KIND_EXCEL, mime=MIME_XLSX, pages=(page,))


def write_adapter(tmp_path, filename: str, body: str):
    (tmp_path / filename).write_text(body, encoding='utf-8')
    return tmp_path


class TestLoadFailFast:
    """坏配置当场拦住启动,绝不静默回落。"""

    def test_missing_directory(self, tmp_path):
        with pytest.raises(ServiceWarning):
            load_adapters(tmp_path / 'not-exist')

    def test_no_yaml_in_directory(self, tmp_path):
        with pytest.raises(ServiceWarning) as excinfo:
            load_adapters(tmp_path)
        assert str(tmp_path) in str(excinfo.value)

    def test_broken_yaml(self, tmp_path):
        write_adapter(tmp_path, 'broken.yaml', 'key: [unclosed\n')
        with pytest.raises(ServiceWarning) as excinfo:
            load_adapters(tmp_path)
        assert 'broken.yaml' in str(excinfo.value)

    def test_missing_fields_section(self, tmp_path):
        write_adapter(tmp_path, 'x.yaml', 'key: x\nname: X\nmode: table\n')
        with pytest.raises(ServiceWarning) as excinfo:
            load_adapters(tmp_path)
        assert 'fields' in str(excinfo.value)

    def test_unknown_field_name(self, tmp_path):
        write_adapter(
            tmp_path,
            'x.yaml',
            'key: x\nmode: table\nfields:\n  date: ["日期"]\n  fundCode: ["代码"]\n  money: ["金额"]\n',
        )
        with pytest.raises(ServiceWarning) as excinfo:
            load_adapters(tmp_path)
        assert 'money' in str(excinfo.value)

    def test_missing_required_field(self, tmp_path):
        write_adapter(tmp_path, 'x.yaml', 'key: x\nmode: table\nfields:\n  fundCode: ["代码"]\n')
        with pytest.raises(ServiceWarning) as excinfo:
            load_adapters(tmp_path)
        assert 'date' in str(excinfo.value)

    def test_bad_mode(self, tmp_path):
        write_adapter(tmp_path, 'x.yaml', 'key: x\nmode: tableLike\nfields:\n  date: ["日期"]\n  fundCode: ["代码"]\n')
        with pytest.raises(ServiceWarning) as excinfo:
            load_adapters(tmp_path)
        assert 'mode' in str(excinfo.value)

    def test_duplicate_key(self, tmp_path):
        body = 'key: dup\nmode: table\nfields:\n  date: ["日期"]\n  fundCode: ["代码"]\n  shares: ["份额"]\n'
        write_adapter(tmp_path, 'a.yaml', body)
        write_adapter(tmp_path, 'b.yaml', body)
        with pytest.raises(ServiceWarning) as excinfo:
            load_adapters(tmp_path)
        assert 'dup' in str(excinfo.value)


class TestBuiltinAdapters:
    """仓库根目录的三份配置能正常加载。"""

    def test_expected_adapters_loaded(self):
        assert {'alipay', 'tiantian', 'generic'} <= set(ADAPTERS)

    def test_generic_has_no_fingerprint(self):
        assert ADAPTERS['generic'].fingerprints == ()

    def test_alipay_mode_is_table(self):
        assert ADAPTERS['alipay'].mode == 'table'


class TestDetectAdapter:
    """适配器选择:指纹优先,零命中回落 generic。"""

    def test_fingerprint_picks_alipay(self):
        document = make_table_document((ALIPAY_HEADER,), lines=('蚂蚁(杭州)基金销售有限公司 基金交易明细',))
        assert detect_adapter(document).key == 'alipay'

    def test_fingerprint_picks_tiantian(self):
        document = make_table_document((('基金代码', '确认份额'),), lines=('天天基金 交易明细',))
        assert detect_adapter(document).key == 'tiantian'

    def test_no_fingerprint_falls_back_to_generic(self):
        document = make_table_document((('基金代码', '确认份额'),), lines=('某小平台 交易明细',))
        assert detect_adapter(document).key == 'generic'

    def test_custom_pool_without_generic_raises(self, tmp_path):
        write_adapter(
            tmp_path,
            'only.yaml',
            'key: only\nmode: table\nfields:\n  date: ["日期"]\n  fundCode: ["代码"]\n  shares: ["份额"]\n',
        )
        pool = load_adapters(tmp_path)
        with pytest.raises(ServiceWarning):
            detect_adapter(make_table_document((('日期', '代码'),), lines=('无指纹',)), pool)


class TestTableExtraction:
    """table 模式:表头定位 + 列名映射(与列号无关)。"""

    def test_column_order_is_irrelevant(self):
        rows = (
            ALIPAY_HEADER,
            ('78.7402', '000001', '', 'A001', '100.00', '华夏成长混合', '0', '2026-05-08'),
        )
        records = extract_records(make_table_document(rows), ADAPTERS['alipay'])
        assert len(records) == 1
        record = records[0]
        assert record['row'] == 2
        assert record['adapter'] == 'alipay'
        assert record['type'] == 'purchase'
        assert record['fund_code'] == '000001'
        assert record['date'] == '2026-05-08'
        assert record['amount'] == 100.0
        assert record['shares'] == 78.7402
        assert record['order_no'] == 'A001'
        assert record['unit_price'] == round(100.0 / 78.7402, 6)

    def test_buy_when_apply_shares_empty_and_sell_otherwise(self):
        rows = (
            ALIPAY_HEADER,
            ('78.7402', '000001', '', 'A001', '100.00', '华夏成长混合', '0', '2026-05-08'),
            ('10.5', '110011', '10.5', 'A002', '21.30', '易方达中小盘', '0.15', '2026-05-09'),
        )
        records = extract_records(make_table_document(rows), ADAPTERS['alipay'])
        assert [record['type'] for record in records] == ['purchase', 'redemption']

    def test_repeated_header_and_total_rows_skipped(self):
        rows = (
            ALIPAY_HEADER,
            ('78.7402', '000001', '', 'A001', '100.00', '华夏成长混合', '0', '2026-05-08'),
            ALIPAY_HEADER,
            ('手续费合计', '', '', '', '0.15', '', '', ''),
        )
        records = extract_records(make_table_document(rows), ADAPTERS['alipay'])
        assert [record['order_no'] for record in records] == ['A001']

    def test_date_split_by_space_is_repaired(self):
        rows = (ALIPAY_HEADER, ('10.5', '110011', '10.5', 'A002', '21.30', '易方达', '0', '2026-05-0 9'))
        records = extract_records(make_table_document(rows), ADAPTERS['alipay'])
        assert records[0]['date'] == '2026-05-09'

    def test_numeric_fund_code_padded(self):
        rows = (
            ('确认份额', '基金代码', '申请份额', '订单号', '确认金额', '基金名称', '手续费', '确认日期'),
            ('80', '1', '', 'A001', '100.00', '华夏成长', '0', '2026-05-08'),
        )
        records = extract_records(make_table_document(rows), ADAPTERS['alipay'])
        assert records[0]['fund_code'] == '000001'

    def test_table_without_header_yields_nothing(self):
        rows = (('甲', '乙'), ('丙', '丁'))
        assert extract_records(make_table_document(rows), ADAPTERS['alipay']) == []


class TestLabelValueMode:
    """labelValue 模式:逐块就近取值,键字段重复即下一笔。"""

    CARD_YAML = (
        'key: card\n'
        'name: 卡片式对账单\n'
        'mode: labelValue\n'
        'fields:\n'
        '  orderNo: ["订单号"]\n'
        '  date: ["确认日期"]\n'
        '  fundCode: ["基金代码"]\n'
        '  fundName: ["基金名称"]\n'
        '  type: ["交易类型"]\n'
        '  amount: ["确认金额"]\n'
        '  shares: ["确认份额"]\n'
    )

    def test_card_blocks_split_by_order_no(self, tmp_path):
        write_adapter(tmp_path, 'card.yaml', self.CARD_YAML)
        adapter = load_adapters(tmp_path)['card']
        lines = (
            '订单号 A001 确认日期 2026-05-08 交易类型 申购',
            '基金名称 华夏成长混合',
            '基金代码 000001',
            '确认金额 100.00 确认份额 78.7402',
            '订单号 A002 确认日期 2026-05-09 交易类型 赎回',
            '基金代码 110011',
            '确认金额 21.30 确认份额 10.5',
        )
        records = extract_records(make_line_document(lines), adapter)
        assert [record['order_no'] for record in records] == ['A001', 'A002']
        assert [record['type'] for record in records] == ['purchase', 'redemption']
        assert records[0]['fund_code'] == '000001'
        assert records[0]['fund_name'] == '华夏成长混合'
        assert records[0]['amount'] == 100.0
        assert records[1]['shares'] == 10.5

    def test_value_on_next_line(self, tmp_path):
        write_adapter(tmp_path, 'card.yaml', self.CARD_YAML)
        adapter = load_adapters(tmp_path)['card']
        lines = (
            '订单号 A001 确认日期 2026-05-08',
            '基金代码 000001',
            '确认金额',
            '100.00',
            '确认份额 78.7402',
        )
        records = extract_records(make_line_document(lines), adapter)
        assert records[0]['amount'] == 100.0

    def test_junk_lines_ignored(self, tmp_path):
        write_adapter(tmp_path, 'card.yaml', self.CARD_YAML)
        adapter = load_adapters(tmp_path)['card']
        lines = ('第 1 页 / 共 2 页', 'www.example.com', '客服电话 400-000-0000')
        assert extract_records(make_line_document(lines), adapter) == []


# 真实截图(支付宝「交易记录」列表)的 OCR 网格行:含页头、名称跨行、OCR 粘连与丢空格的时间戳
LIST_ITEM_LINES = (
    '14:49支 530K/s4G 4G',
    '全部持有 收益明细 交易记录',
    '明细 △晋 全部',
    '定投 基金|广发纳斯达克100ETF 2.00元',
    '联接(QDII)A 交易进行中',
    '2026-09-17 09:36:58',
    '买入 基金|易方达科融混合 15.00元',
    '2026-09-1609:33:11',
    '买入基 基金|万家品质生活灵活配置 15.00元',
    '混合A',
    '2026-09-14 09:33:58',
)


class TestListItem:
    """listItem 模式:方向词开条、后续行归入本条(用项目根目录那份真实适配配置)。"""

    adapter = ADAPTERS['alipay_trade_list']

    def test_fingerprint_selects_list_adapter(self):
        assert detect_adapter(make_line_document(LIST_ITEM_LINES)).key == 'alipay_trade_list'

    def test_records_from_real_ocr_lines(self):
        records = extract_records(make_line_document(LIST_ITEM_LINES), self.adapter)
        assert [record['fund_name'] for record in records] == [
            '广发纳斯达克100ETF联接(QDII)A',  # 状态文案与名称同行的续行要剔干净
            '易方达科融混合',
            '万家品质生活灵活配置混合A',  # OCR 粘连的「买入基」+ 跨行名称
        ]
        assert [record['date'] for record in records] == ['2026-09-17', '2026-09-16', '2026-09-14']
        assert [record['amount'] for record in records] == [2.0, 15.0, 15.0]
        assert all(record['type'] == 'purchase' for record in records)
        assert records[0]['row'] == 4  # 行号 = OCR 网格行序

    def test_page_header_alone_yields_nothing(self):
        lines = ('全部持有 收益明细 交易记录', '明细 △晋 全部')
        assert extract_records(make_line_document(lines), self.adapter) == []

    def test_cancelled_block_skipped(self):
        lines = ('定投 基金|某某测试基金 2.00元', '2026-09-13 09:00:00', '交易失败')
        assert extract_records(make_line_document(lines), self.adapter) == []

    def test_amount_ignores_digits_inside_fund_name(self):
        """基金名里带数字(100ETF)时不能把 100 当金额。"""
        lines = ('买入 基金|某纳斯达克100ETF联接A 15.00元', '2026-09-16 10:00:00')
        records = extract_records(make_line_document(lines), self.adapter)
        assert records[0]['amount'] == 15.0

    def test_dividend_rows_split_by_amount_or_shares(self):
        """分红行(2026-09-23):App 交易记录里类型词就是「分红」,两态混排。

        「5.80元」= 现金分红(0 份额 + 金额取负,冲减持仓成本)、「1.95份」= 红利再投资
        (0 成本买入,份额涨、钱不动)。份额靠 share_units 的「份」认出来,金额靠「元」。
        """
        lines = (
            '全部持有 收益明细 交易记录',
            '分红 基金|银华鑫锐灵活配置混合(LOF)A 5.80元',
            '2022-08-19 09:33:58',
            '分红 基金|招商中证白酒指数(LOF)A 1.95份',
            '2022-08-19 09:34:01',
        )
        records = extract_records(make_line_document(lines), self.adapter)
        cash, reinvest = records
        assert (cash['dividend'], cash['type'], cash['shares'], cash['amount']) == (
            '现金分红', 'purchase', 0.0, -5.8,
        )
        assert (reinvest['dividend'], reinvest['type'], reinvest['shares'], reinvest['amount']) == (
            '红利再投资', 'purchase', 1.95, 0.0,
        )

    def test_filter_bar_with_dividend_word_opens_no_block(self):
        """顶部筛选栏含「分红」(明细 基金 分红▾):靠 skip_when_all_of 拦掉,不产生记录。"""
        lines = ('全部持有 收益明细 交易记录', '明细 基金 分红')
        assert extract_records(make_line_document(lines), self.adapter) == []

    def test_amount_with_prefix_currency_symbol(self):
        lines = ('买入 基金|某某混合A ¥15.00', '2026-09-16 10:00:00')
        records = extract_records(make_line_document(lines), self.adapter)
        assert records[0]['amount'] == 15.0
        assert records[0]['fund_name'] == '某某混合A'


# 天天基金 App「交易查询」列表截图的两页真图 OCR 行(逐字抄自实测,含 OCR 抖动:空格被吃、图标误识)
TIANTIAN_BUY_LINES = (
    '交易查询  活期宝',
    '在途 全部',
    '近1年交易总览',
    '25次 10次  0次 3次',
    '买入① 卖出①  定投 分红',
    '类型 状态  时间 银行卡',
    '2026年07月',
    '买 买入   25.00元',
    '国泰黄金ETF联接A',
    '07-01 14:53:38   成功',
    '2026年06月',
    '目= 红利再投资   30.97份',
    '鹏华丰禄债券',
    '06-30 05:26:10   成功',
    '红利再投资   2.58份',
    '鹏华丰禄债券',
    '06-30 05:26:10   成功',
    '买 买入   25.00元',
    '国泰黄金ETF联接A',
    '06-1014:40:29   成功',  # OCR 把「06-10 14:40:29」的空格吃了
    '2026年05月',
)

TIANTIAN_SELL_LINES = (
    '交易查询  活期宝',
    '近1年交易总览',
    '25次 10次  0次 3次',
    '买入① 卖出⑨  定投 分红',
    '卖出 状态  时间 银行卡',
    '2026年01月',
    '卖 卖出回银行卡   5.93份',
    '国泰黄金ETF联接A',
    '01-17 10:08:26   已撤单(无需支付)',
    '2025年11月',
    '卖 卖出回银行卡   52.17元',
    '国投瑞银白银期货(LOF)C',
    '11-2414:51:32   成功',
    '卖 卖出回银行卡   53.14元',
    '国投瑞银白银期货(LOF)C',
    '11-1714:55:51   成功',
    '2025年10月',
    '卖 卖出回银行卡   34.83元',
    '国泰黄金ETF联接A',
    '10-2413:33:07   成功',
)


class TestTiantianTradeQuery:
    """天天基金 App「交易查询」列表截图:分组标题给年份、名称只取续行、份额认「份」。

    夹具是两张真图的 OCR 原文——这张图的坑全在 OCR 结果里(月份标题、无年份日期、
    图标误识成的「目=」、顶部汇总行、列头行),直接锁这几条真行即可,不必另造。
    """

    adapter = ADAPTERS['tiantian_trade_query']

    def test_fingerprint_selects_this_adapter(self):
        """App 页面里不出现平台名:靠 App 独有词选中,而不是落到兜底的 generic。"""
        assert detect_adapter(make_line_document(TIANTIAN_BUY_LINES)).key == 'tiantian_trade_query'
        assert detect_adapter(make_line_document(TIANTIAN_SELL_LINES)).key == 'tiantian_trade_query'

    def test_buy_rows_keep_name_and_date_clean(self):
        records = extract_records(make_line_document(TIANTIAN_BUY_LINES), self.adapter)
        buys = [record for record in records if not record.get('dividend')]
        assert [(record['fund_name'], record['amount'], record['date']) for record in buys] == [
            ('国泰黄金ETF联接A', 25.0, '2026-07-01'),
            ('国泰黄金ETF联接A', 25.0, '2026-06-10'),  # 日期空格被 OCR 吃掉也要认出来
        ]
        assert all(record['type'] == 'purchase' for record in buys)

    def test_month_header_does_not_pollute_name(self):
        """月份标题既不能进名称(否则认不出基金),也不能被上一条吞掉。"""
        records = extract_records(make_line_document(TIANTIAN_BUY_LINES), self.adapter)
        assert [record['fund_name'] for record in records] == [
            '国泰黄金ETF联接A',
            '鹏华丰禄债券',
            '鹏华丰禄债券',
            '国泰黄金ETF联接A',
        ]

    def test_dividend_rows_split_by_shares(self):
        """截图里的红利行不再跳过:有份额=红利再投资(0 成本买入),与表格型同一套分流(2026-09-23)。"""
        records = extract_records(make_line_document(TIANTIAN_BUY_LINES), self.adapter)
        dividends = [record for record in records if record.get('dividend')]
        assert [(r['dividend'], r['type'], r['fund_name'], r['shares'], r['amount']) for r in dividends] == [
            ('红利再投资', 'purchase', '鹏华丰禄债券', 30.97, 0.0),
            ('红利再投资', 'purchase', '鹏华丰禄债券', 2.58, 0.0),
        ]
        assert all(not record.get('unsupported') for record in records)
        # listItem 的基金代码由预览流程按名称解析后才有,这里只钉「方向不再有判不了的问题」
        _, errors, warnings = validate_records(records)
        assert [i.field for i in errors if i.field == 'type'] == []
        assert [i.field for i in warnings if i.field == 'type'] == []  # 分红行方向由规则定死,不算「猜」

    def test_summary_and_column_header_rows_yield_no_record(self):
        records = extract_records(make_line_document(TIANTIAN_BUY_LINES), self.adapter)
        assert 7 not in [record['row'] for record in records]  # 顶部汇总行 + 列头行那一块
        assert all('①' not in record['fund_name'] for record in records)

    def test_sell_rows_cross_year_and_skip_cancelled(self):
        records = extract_records(make_line_document(TIANTIAN_SELL_LINES), self.adapter)
        assert [(record['type'], record['amount'], record['date']) for record in records] == [
            ('redemption', 52.17, '2025-11-24'),
            ('redemption', 53.14, '2025-11-17'),
            ('redemption', 34.83, '2025-10-24'),  # 年份只能来自分组标题(同屏跨 2026 / 2025)
        ]
        assert [record['fund_name'] for record in records] == [
            '国投瑞银白银期货(LOF)C',
            '国投瑞银白银期货(LOF)C',
            '国泰黄金ETF联接A',
        ]
        assert all(record['shares'] == 0 for record in records)  # 卖出行只给金额,份额后续按净值反推

    def test_yearless_date_without_group_header_is_left_empty(self):
        """没有分组标题就不猜年份:日期留空,交给校验层报「交易日期无法解析」。"""
        lines = tuple(line for line in TIANTIAN_BUY_LINES if '年' not in line)
        records = extract_records(make_line_document(lines), self.adapter)
        assert records and all(record['date'] is None for record in records)


# 天天基金《对账单》PDF 的真实网格行(pdfplumber 读出的 extract_tables 结果,逐格照抄;
# 银行卡列换成占位符,不把个人数据写进仓库)
TIANTIAN_BILL_HEADER = (
    '确认日期',
    '基金代码',
    '基金简称',
    '业务类型',
    '确认状态',
    '确认份额',
    '确认金额',
    '手续费',
    '确认净值',
    '关联银行卡',
)
TIANTIAN_BILL_ROWS = (
    TIANTIAN_BILL_HEADER,
    ('2021-08-02', '005827', '易方达蓝筹精选混合', '卖基金', '成功', '12.00', '29.81', '0.15', '2.4967', '某银行 | 0000'),
    ('2021-07-27', '161005', '富国天惠成长混合 (LOF)A', '卖基金', '成功', '20.27', '70.86', '0.37', '3.5143', '某银行 | 0000'),
)
# 第 2 页的续页:同样是 10 列,但没有表头行(pdfplumber 读出来就是纯数据)
TIANTIAN_BILL_CONTINUATION = (
    ('2021-05-10', '161005', '富国天惠成长混合 (LOF)A', '买基金', '成功', '2.86', '10.00', '0.01', '3.4961', '某银行 | 0000'),
    ('2021-04-20', '005827', '易方达蓝筹精选混合', '修改分红方式', '成功', '0.00', '0.00', '0.00', '0.0000', ''),
    ('2021-03-18', '005827', '易方达蓝筹精选混合', '买基金', '成功', '3.50', '10.00', '0.01', '2.8582', '某银行 | 0000'),
)
# 另一张不同列数的表(投顾,5 列)且同样没有表头:不许被当成交易表的样子解析
TIANTIAN_ADVISOR_ROWS = (('2021-01-01', '某投顾组合', '某某策略', '100.00', '某银行 | 0000'),)
# 分红明细表:表头含「分红方式」→ 整表按「暂不支持导入」标记
TIANTIAN_DIVIDEND_ROWS = (
    ('确认日期', '基金代码', '基金简称', '分红方式', '分红金额', '分红再投份额', '确认净值'),
    ('2021-03-29', '161005', '富国天惠成长混合(LOF)A', '现金分红', '0.42', '--', '0.0000'),
)


def make_tables_document(tables: tuple[tuple[tuple[str, ...], ...], ...]) -> DocumentContent:
    """一份文档里按顺序放多张表(测「续页无表头继承上一张表的列映射」)。"""
    document_tables = tuple(
        DocumentTable(page_no=1, rows=rows, row_refs=tuple(range(1, len(rows) + 1)), layer=LAYER_TEXT)
        for rows in tables
    )
    page = DocumentPage(page_no=1, lines=(), tables=document_tables, layer=LAYER_TEXT)
    return DocumentContent(kind=KIND_EXCEL, mime=MIME_XLSX, pages=(page,))


class TestTiantianBillPdf:
    """天天基金《对账单》PDF:名称列叫「基金简称」、续页不重复表头、分红明细整表跳过。

    这三条都是同一次实测踩出来的:名称全是空(前端显示「—」)、第 2 页 10 条交易被静默丢掉、
    分红行报「买卖方向无法判定」。
    """

    adapter = ADAPTERS['tiantian']

    def test_fund_name_from_short_name_column(self):
        """导出件里名称列叫「基金简称」:别名对不上就会整列为空(折行的长名是一整格,不用拼)。"""
        records = extract_records(make_table_document(TIANTIAN_BILL_ROWS), self.adapter)
        assert [record['fund_name'] for record in records] == ['易方达蓝筹精选混合', '富国天惠成长混合 (LOF)A']
        assert [record['fund_code'] for record in records] == ['005827', '161005']

    def test_headerless_continuation_inherits_columns(self):
        """续页没有表头 → 沿用上一张同宽表的列映射,不再整表丢掉。"""
        document = make_tables_document((TIANTIAN_BILL_ROWS, TIANTIAN_BILL_CONTINUATION))
        records = extract_records(document, self.adapter)
        assert [record['date'] for record in records] == ['2021-08-02', '2021-07-27', '2021-05-10', '2021-03-18']
        assert {record['fund_name'] for record in records} == {'易方达蓝筹精选混合', '富国天惠成长混合 (LOF)A'}
        assert all(record['type'] in ('purchase', 'redemption') for record in records)

    def test_non_transaction_row_is_skipped(self):
        """「修改分红方式」不动钱(份额/金额/净值全 0),按非交易整行跳过。"""
        document = make_tables_document((TIANTIAN_BILL_ROWS, TIANTIAN_BILL_CONTINUATION))
        records = extract_records(document, self.adapter)
        assert '2021-04-20' not in [record['date'] for record in records]

    def test_different_width_table_is_not_inherited(self):
        """列数不一致的表一律不继承——宁可少抽,也不能把投顾表按交易表解析。"""
        document = make_tables_document((TIANTIAN_BILL_ROWS, TIANTIAN_ADVISOR_ROWS))
        records = extract_records(document, self.adapter)
        assert [record['fund_code'] for record in records] == ['005827', '161005']

    def test_dividend_table_splits_into_two_forms(self):
        """分红明细表**不再整表跳过**:有份额 = 红利再投资(0 成本买入),只有金额 = 现金分红(金额取负)。

        2026-09-22 修:此前 unsupported_words 命中该表**表头**「分红方式」→ 整表被当「账本表达不了」
        跳过,003547 少记 43.32 份红利再投(持有收益被算成 -8.09,实际 +37.35)。
        """
        rows = TIANTIAN_DIVIDEND_ROWS + (
            ('2025-07-03', '003547', '鹏华丰禄债券', '红利再投资', '--', '5.86', '1.0419'),
        )
        records = extract_records(make_tables_document((rows,)), self.adapter)
        assert [record.get('unsupported') for record in records] == [None, None]
        cash, reinvest = records
        assert (cash['dividend'], cash['type'], cash['shares'], cash['amount']) == ('现金分红', 'purchase', 0.0, -0.42)
        assert (reinvest['dividend'], reinvest['type'], reinvest['shares'], reinvest['amount']) == (
            '红利再投资', 'purchase', 5.86, 0.0,
        )


ALIPAY_TYPE_HEADER = (
    '确认份额', '基金代码', '申请份额', '订单号', '确认金额', '基金名称', '手续费', '确认日期', '交易类型',
)


def alipay_typed_row(
    type_word: str,
    *,
    code: str = '000001',
    apply_shares: str = '',
    tx_date: str = '2026-05-08',
    shares: str = '78.7402',
    amount: str = '100.00',
    name: str = '华夏成长混合',
) -> tuple[str, ...]:
    return (shares, code, apply_shares, 'A001', amount, name, '0', tx_date, type_word)


class TestAlipayTransactionType:
    """支付宝「交易类型」列:方向主判据;认不出的类型(用户跨TA转换)退回申请份额判定。

    2026-09-20 之前 `alipay.yaml` 没映射这一列,于是**每行**都在靠「申请份额是否为空」猜方向,
    实测把「机构分红」判成买入、把「用户买入」判成赎回;类型列里的「用户跨TA转换」才是真需要
    靠申请份额分流的那一类。
    """

    adapter = ADAPTERS['alipay']

    def test_type_column_wins_over_apply_shares(self):
        """类型列说买入就是买入——哪怕申请份额列有值;说卖出就是卖出——哪怕它是空的。"""
        rows = (
            ALIPAY_TYPE_HEADER,
            alipay_typed_row('用户买入', code='000001', apply_shares='78.7402'),
            alipay_typed_row('用户卖出', code='110011', apply_shares=''),
        )
        records = extract_records(make_table_document(rows), self.adapter)
        assert [record['type'] for record in records] == ['purchase', 'redemption']

    def test_ding_tou_buy_is_purchase(self):
        records = extract_records(
            make_table_document((ALIPAY_TYPE_HEADER, alipay_typed_row('定投买入'))), self.adapter
        )
        assert records[0]['type'] == 'purchase'

    def test_ding_tou_sell_is_redemption(self):
        """「定投卖出」同时含买入词(定投)与卖出词(卖)→ 必须判赎回。

        2026-09-22 实测(蚂蚁对账单 78 页):先判买入词会把这两行判成买入,持仓永远清不掉;
        而它们的申请份额列是有值的,走兜底本来就能判对——坏点就是这个优先级。
        """
        rows = (
            ALIPAY_TYPE_HEADER,
            alipay_typed_row('定投卖出', code='013577', apply_shares='1.11', shares='1.11', amount='1.18'),
            alipay_typed_row('定投卖出', code='014097', apply_shares='2.68', shares='2.68', amount='2.88'),
        )
        records = extract_records(make_table_document(rows), self.adapter)
        assert [record['type'] for record in records] == ['redemption', 'redemption']

    def test_ding_tou_sell_wins_even_when_apply_shares_empty(self):
        """类型列认得出方向就用它,哪怕申请份额是空的(否则会退回兜底判成买入)。"""
        records = extract_records(
            make_table_document((ALIPAY_TYPE_HEADER, alipay_typed_row('定投卖出', apply_shares=''))),
            self.adapter,
        )
        assert records[0]['type'] == 'redemption'

    @pytest.mark.parametrize(
        ('type_word', 'expected'),
        [
            ('用户买入', 'purchase'),
            ('定投买入', 'purchase'),
            ('用户卖出', 'redemption'),
            ('定投卖出', 'redemption'),
            ('转换转出', 'redemption'),
        ],
    )
    def test_direction_per_real_type_word(self, type_word, expected):
        """源文件里实际出现过的类型逐个钉住方向(表驱动,新增词只加一行)。"""
        records = extract_records(
            make_table_document((ALIPAY_TYPE_HEADER, alipay_typed_row(type_word))), self.adapter
        )
        assert records[0]['type'] == expected

    def test_cross_ta_conversion_falls_back_to_apply_shares(self):
        """「用户跨TA转换」不含买/卖词 → 按申请份额空不空分转出/转入,而不是判不了被拦。"""
        rows = (
            ALIPAY_TYPE_HEADER,
            alipay_typed_row('用户跨TA转换', code='000001', apply_shares=''),
            alipay_typed_row('用户跨TA转换', code='110011', apply_shares='10.5'),
        )
        records = extract_records(make_table_document(rows), self.adapter)
        assert [record['type'] for record in records] == ['purchase', 'redemption']

    def test_dividend_rows_split_by_shares_or_amount(self):
        """机构分红按「有份额还是有金额」分流:份额 → 0 成本买入;金额 → 0 份额 + 负金额(冲减成本)。

        同一个词在真实文件里混着两种形态(「机构分红」既可能是红利再投、也可能是现金分红),
        从前分不开只能整行跳过;现在靠该行的份额/金额自动分流,一个字节都不丢。
        """
        rows = (
            ALIPAY_TYPE_HEADER,
            alipay_typed_row('机构分红', code='003095', apply_shares='/', shares='0.92', amount='0.00'),
            alipay_typed_row('机构分红', code='003547', apply_shares='/', shares='0.00', amount='1.18'),
        )
        records = extract_records(make_table_document(rows), self.adapter)
        reinvest, cash = records
        assert (reinvest['dividend'], reinvest['type'], reinvest['shares'], reinvest['amount']) == (
            '红利再投资', 'purchase', 0.92, 0.0,
        )
        assert (cash['dividend'], cash['type'], cash['shares'], cash['amount']) == ('现金分红', 'purchase', 0.0, -1.18)
        kept, errors, warnings = validate_records(records)
        assert len(kept) == 2 and not errors
        # 分红行的方向由分流规则定死,不算「靠申请份额猜的」→ 不该冒那条告警
        assert [issue for issue in warnings if issue.field == 'type'] == []


class TestSplitDayDate:
    """日期格里的「日」被空格切开:真实导出件 1272 格是这个形状,其中 932 行曾被静默解错。

    `2021/07/2 6 09:33` 是 **7 月 26 日**(同一格还带时间);旧实现走 `_date_candidates` 的
    「第一个 token」捷径 —— `2021/07/2` 用 `%Y/%m/%d` **能成功**解析成 2 日,于是永远到不了
    下方的去空格兜底,**日的十位被静默丢弃**(只有日首位为 0 时才落到兜底、反而解对)。
    这一组用例按真实形态钉住修复,并覆盖 5 类规整形态的「不回归」。
    """

    adapter = ADAPTERS['alipay']

    @pytest.mark.parametrize(
        ('raw', 'expected'),
        [
            ('2021/07/2 6 09:33', '2021-07-26'),  # 26:旧实现解成 02
            ('2021/08/1 8 09:33', '2021-08-18'),  # 18:旧实现解成 01(011102 的那笔卖出)
            ('2021/12/2 0 09:33', '2021-12-20'),  # 20:旧实现解成 02
            ('2021/07/1 0 09:33', '2021-07-10'),  # 10:旧实现解成 01
            ('2021/07/3 0 09:33', '2021-07-30'),  # 30:旧实现解成 03
            ('2021/08/0 4 09:33', '2021-08-04'),  # 日首位是 0:旧实现也解对,不能改坏
            ('2026-05-0 9', '2026-05-09'),  # 既有的「被空格切碎」形态
            ('2026-05-08', '2026-05-08'),  # 规整:破折号
            ('2026/05/08 10:23', '2026-05-08'),  # 规整:带时间
            ('20260508', '2026-05-08'),  # 规整:纯数字串
        ],
    )
    def test_split_day_keeps_both_digits(self, raw, expected):
        assert _parse_date(raw, self.adapter) == expected

    def test_still_unparseable_after_compaction_is_not_guessed(self):
        """去空格后仍是非法日期(13 月)→ 判为日期但不产出日期,交给校验层拦。"""
        assert _parse_date('2021/13/0 5 09:33', self.adapter) is None

    def test_yearless_form_is_not_affected(self):
        """无年份形态不受影响:支付宝没配 `date_without_year_patterns`,日期不全就**不产出**(不猜年份)。

        同时钉住新分支不越界:去掉数字间空格后的 `07-0114:53:38` 里没有 4 位年份,不能被当日期解出来。
        """
        assert _parse_date('07-01 14:53:38 成功', self.adapter) is None
        assert _parse_date('07-01 14:53:38 成功', self.adapter, '2026') is None


class TestPageBreakContinuation:
    """跨页折行:页边界把一条记录的**单元格**从中间切断,续行落在下一页表首,只有跨表才能回补。

    2026-09-20 对真实导出件(78 页)实测的形态——不是「两行各带一半列」,而是:
      末页(:9 行16)  ['78.74', '015861', ..., '2026/03/0', '用户买入']   ← 日期头 + 代码 + 金额
      下页首行        ['', '', '', '', '', '白酒指数 (LOF)A', '', '5 13:45', '']  ← 名称尾 + 日期尾
    拼起来才是 `招商中证白酒指数 (LOF)A` / `2026-03-05 13:45`。同一文件命中 50 条续行;其中 5 条的父
    记录日期**取不到**(被拦),另有 8 条父记录日期**被静默解析错**(`2026/03/2` 当成 2 日,实为 25 日)。
    """

    adapter = ADAPTERS['alipay']

    def test_name_tail_is_absorbed_into_previous_record(self):
        """名称尾巴回补上一条记录,续行自身不产出记录(否则会报「基金代码为空」)。"""
        tables = (
            (ALIPAY_TYPE_HEADER, alipay_typed_row('用户买入', name='华夏有色 金属')),
            (('', '', '', 'A001', '', 'ETF联接 C', '', '', ''),),
        )
        records = extract_records(make_tables_document(tables), self.adapter)
        assert len(records) == 1
        assert records[0]['fund_name'] == '华夏有色 金属ETF联接 C'
        assert records[0]['fund_code'] == '000001' and records[0]['date'] == '2026-05-08'

    def test_split_date_that_could_not_be_parsed_is_repaired(self):
        """页末行只剩日期头(`2026/03/0`,日期 0 不合法)→ 拼上尾巴后拿到真日期。"""
        tables = (
            (ALIPAY_TYPE_HEADER, alipay_typed_row('用户买入', name='招商中证', tx_date='2026/03/0')),
            (('', '', '', '', '', '白酒指数 (LOF)A', '', '5 13:45', ''),),
        )
        records = extract_records(make_tables_document(tables), self.adapter)
        assert len(records) == 1
        assert records[0]['date'] == '2026-03-05'
        assert records[0]['fund_name'] == '招商中证白酒指数 (LOF)A'

    def test_silently_wrong_date_is_corrected(self):
        """最隐蔽的一种:`2026/03/2` 自己就能解析成 2 日(不报错),拼上尾巴才回到 25 日。"""
        head_only = (ALIPAY_TYPE_HEADER, alipay_typed_row('用户买入', tx_date='2026/03/2'))
        assert extract_records(make_tables_document((head_only,)), self.adapter)[0]['date'] == '2026-03-02'

        tables = (head_only, (('', '', '', '', '', '白酒指数 (LOF)A', '', '5 13:45', ''),))
        assert extract_records(make_tables_document(tables), self.adapter)[0]['date'] == '2026-03-25'

    def test_unparseable_after_join_keeps_original_date(self):
        """拼接后仍解析不出 → 保持原值(宁可留着让校验层拦,也不猜一个日期出来)。"""
        tables = (
            (ALIPAY_TYPE_HEADER, alipay_typed_row('用户买入', tx_date='2026/13/0')),
            (('', '', '', '', '', '白酒指数 (LOF)A', '', '5 13:45', ''),),
        )
        records = extract_records(make_tables_document(tables), self.adapter)
        assert len(records) == 1 and records[0]['date'] is None

    def test_row_with_own_fields_is_never_absorbed(self):
        """带自己字段的行(有代码或金额)一律按正常行处理,绝不当成续行吞掉。"""
        tables = (
            (ALIPAY_TYPE_HEADER, alipay_typed_row('用户买入', tx_date='2026-05-08')),
            (('78.7402', '110011', '', 'A002', '200.00', '另一只基金', '0', '', '用户卖出'),),
        )
        records = extract_records(make_tables_document(tables), self.adapter)
        assert len(records) == 2
        assert records[1]['fund_code'] == '110011' and records[1]['type'] == 'redemption'

    def test_first_row_fragment_without_previous_record_is_kept(self):
        """没有上一条记录可回补时(如首表首行就是碎片)不吞掉,照常产出交给校验层报问题。"""
        tables = ((ALIPAY_TYPE_HEADER, ('', '', '', 'A001', '', 'ETF联接 C', '', '', '')),)
        records = extract_records(make_tables_document(tables), self.adapter)
        assert len(records) == 1 and records[0]['fund_code'] == '' and records[0]['date'] is None

    def test_over_long_name_tail_is_dropped_not_appended(self):
        """名称尾巴过长(>20 字)多半不是折行 → 只丢不接,别把两行名字拼成第三个。"""
        tables = (
            (ALIPAY_TYPE_HEADER, alipay_typed_row('用户买入', name='华夏有色 金属')),
            (('', '', '', '', '', '这显然不是折行尾巴而是一整段全新的基金名称文本', '', '5 13:45', ''),),
        )
        records = extract_records(make_tables_document(tables), self.adapter)
        assert len(records) == 1
        assert records[0]['fund_name'] == '华夏有色 金属'
        # 父记录日期本来就是完整的 → 拼上尾巴不改变结果(只有真的被切断过才会变)
        assert records[0]['date'] == '2026-05-08'


# ===== 跨TA转换:真实导出件取证的 26 条(13 对) =====

# 表头比 ALIPAY_TYPE_HEADER 多一列「申请金额」(蚂蚁明细 col6):两列成对出现才有下面的双列口径
ALIPAY_APPLY_HEADER = (
    '确认份额', '基金代码', '申请金额', '申请份额', '订单号', '确认金额', '基金名称', '手续费', '确认日期', '交易类型',
)

CONVERSION_TYPE = '用户跨TA转换'

# 真实取值(2026-10 从使用者导出件抽取):(基金代码, 申请金额, 申请份额, 确认份额, 确认金额, 期望方向)
# 一次跨TA转换 = 转出腿(申请份额=份额、申请金额 0.00)+ 转入腿(申请金额=钱、申请份额 '/'),两条腿同订单号
CROSS_TA_REAL_ROWS = (
    # 2026-03-19 批次
    ('004814', '48.86', '/', '21.74', '48.86', 'purchase'),
    ('090013', '0.00', '24.11', '24.11', '49.88', 'redemption'),
    ('025857', '51.60', '/', '39.79', '51.60', 'purchase'),
    ('007466', '0.00', '31.18', '31.18', '52.01', 'redemption'),
    ('022070', '46.04', '/', '34.91', '46.04', 'purchase'),
    ('017953', '0.00', '27.90', '27.90', '47.14', 'redemption'),
    ('016708', '46.04', '/', '25.44', '46.04', 'purchase'),
    ('017953', '0.00', '27.90', '27.90', '47.14', 'redemption'),
    # 2026-03-15 / 2024-01-30 / 2023-03-01 / 2021-11-01 批次
    ('023918', '0.00', '72.04', '72.04', '98.70', 'redemption'),
    ('023917', '90.17', '/', '65.63', '90.17', 'purchase'),
    ('001736', '0.00', '23.67', '23.67', '61.68', 'redemption'),
    ('519002', '59.07', '/', '14.84', '59.07', 'purchase'),
    ('011103', '11.23', '/', '17.07', '11.23', 'purchase'),
    ('001736', '0.00', '4.50', '4.50', '11.70', 'redemption'),
    ('320007', '11.23', '/', '11.31', '11.23', 'purchase'),
    ('001736', '0.00', '4.50', '4.50', '11.70', 'redemption'),
    ('519756', '11.23', '/', '8.37', '11.23', 'purchase'),
    ('001736', '0.00', '4.50', '4.50', '11.70', 'redemption'),
    ('003095', '11.23', '/', '7.03', '11.23', 'purchase'),
    ('001736', '0.00', '4.50', '4.50', '11.70', 'redemption'),
    ('519704', '0.00', '20.00', '20.00', '93.47', 'redemption'),
    ('519756', '90.11', '/', '45.11', '90.11', 'purchase'),
    ('090018', '0.00', '2.00', '2.00', '13.02', 'redemption'),
    ('162605', '12.54', '/', '4.35', '12.54', 'purchase'),
    ('002707', '0.00', '6.00', '6.00', '12.25', 'redemption'),
    ('003095', '10.64', '/', '3.25', '10.64', 'purchase'),
)


def alipay_apply_row(
    type_word: str,
    *,
    code: str,
    apply_amount: str,
    apply_shares: str,
    shares: str,
    amount: str,
    tx_date: str = '2026-05-08',
    name: str = '某基金',
) -> tuple[str, ...]:
    """按 ALIPAY_APPLY_HEADER 的列序造一行(含申请金额列)。"""
    return (shares, code, apply_amount, apply_shares, 'A001', amount, name, '0', tx_date, type_word)


class TestCrossTaConversion:
    """「用户跨TA转换」不含买/卖词 → 靠「申请金额 / 申请份额」两列分方向。

    真实文件的编码是**互斥**的:转入腿只申请金额(申请份额写 '/'),转出腿只申请份额
    (申请金额写 '0.00')。所以判定必须两列一起看,且「0」要当成没填——真文件里就有 4 条
    「用户买入」把申请份额写成 0.00,它们今天是靠类型列才没判反,而跨TA转换没有类型词可依。
    """

    adapter = ADAPTERS['alipay']

    @pytest.mark.parametrize(('code', 'apply_amount', 'apply_shares', 'shares', 'amount', 'expected'), CROSS_TA_REAL_ROWS)
    def test_real_rows_direction(self, code, apply_amount, apply_shares, shares, amount, expected):
        """26 条真实跨TA行逐条钉住方向(表驱动:换文件/换平台只改数据不改断言)。"""
        rows = (
            ALIPAY_APPLY_HEADER,
            alipay_apply_row(
                CONVERSION_TYPE,
                code=code,
                apply_amount=apply_amount,
                apply_shares=apply_shares,
                shares=shares,
                amount=amount,
            ),
        )
        records = extract_records(make_table_document(rows), self.adapter)
        assert [record['type'] for record in records] == [expected]

    def test_real_file_is_balanced(self):
        """13 对 = 13 买 + 13 卖:一次转换必须两条腿各判一个方向,不能两边都判成同一边。"""
        rows = (
            ALIPAY_APPLY_HEADER,
            *[
                alipay_apply_row(
                    CONVERSION_TYPE,
                    code=code,
                    apply_amount=apply_amount,
                    apply_shares=apply_shares,
                    shares=shares,
                    amount=amount,
                )
                for code, apply_amount, apply_shares, shares, amount, _ in CROSS_TA_REAL_ROWS
            ],
        )
        types = [record['type'] for record in extract_records(make_table_document(rows), self.adapter)]
        assert types.count('purchase') == 13
        assert types.count('redemption') == 13

    @pytest.mark.parametrize(
        ('apply_amount', 'apply_shares', 'expected'),
        [
            ('1.28', '0.00', 'purchase'),     # 真文件里「用户买入」就写成 0.00
            ('46.04', '/', 'purchase'),       # 占位符
            ('46.04', '／', 'purchase'),      # 全角占位符(OCR 常见)
            ('0.00', '4.50', 'redemption'),   # 转出腿
            ('0.00', '', 'purchase'),         # 两列都没填 → 退回单列口径判买入
        ],
    )
    def test_zero_and_placeholders_count_as_unfilled(self, apply_amount, apply_shares, expected):
        """「没申请」的写法不只有空串:0.00 与全角占位符同样代表这一列没数。"""
        rows = (
            ALIPAY_APPLY_HEADER,
            alipay_apply_row(
                '未知类型', code='000001', apply_amount=apply_amount, apply_shares=apply_shares,
                shares='1.00', amount='1.00',
            ),
        )
        records = extract_records(make_table_document(rows), self.adapter)
        assert [record['type'] for record in records] == [expected]

    def test_single_column_adapter_still_works(self):
        """没映射「申请金额」的平台(表头里没这一列):单列口径照旧,0.00 也算没填。"""
        rows = (
            ALIPAY_TYPE_HEADER,
            alipay_typed_row(CONVERSION_TYPE, code='000001', apply_shares='0.00'),
            alipay_typed_row(CONVERSION_TYPE, code='110011', apply_shares='10.5'),
        )
        records = extract_records(make_table_document(rows), self.adapter)
        assert [record['type'] for record in records] == ['purchase', 'redemption']

    @pytest.mark.parametrize(('type_word', 'expected'), [('转换转入', 'purchase'), ('转换转出', 'redemption')])
    def test_conversion_verbs_decide_direction(self, type_word, expected):
        """写明了「转入/转出」就不用猜:动词定方向(与「定投卖出」同一条卖出词优先口径)。"""
        records = extract_records(
            make_table_document((ALIPAY_TYPE_HEADER, alipay_typed_row(type_word, apply_shares='9.99'))),
            self.adapter,
        )
        assert records[0]['type'] == expected
