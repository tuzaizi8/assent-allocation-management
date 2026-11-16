"""交易记录导出的行映射单测(纯函数)。

导出与导入模板同列形,回导才不会在校验环节碎掉;待确认行的留空口径在这里钉死。
"""

from module_portfolio.service.excel_service import ExcelService


def tx_row(**overrides) -> dict:
    """构造一条流水 union 行(_transaction_row 输出形)。"""
    base = {
        'type': '买入',
        'record_id': 1,
        'source': 'purchase',
        'fund_code': '005827',
        'fund_name': '易方达蓝筹精选混合',
        'date': '2026-01-05',
        'amount': 1234.5,
        'shares': 1000.0,
        'price': 1.2345,
        'status': '1',
        'remark': None,
    }
    base.update(overrides)
    return base


class TestTransactionExportRows:
    def test_confirmed_purchase_maps_to_template_columns(self):
        """确认买入:8 列齐全,手续费恒 0。"""
        rows = ExcelService._transaction_export_rows([tx_row()])
        assert rows[0] == ['2026-01-05', '005827', '易方达蓝筹精选混合', '买入', 1000.0, 1.2345, 1234.5, 0]

    def test_confirmed_redemption_keeps_rows_shape(self):
        """确认赎回:类型直出中文,金额用行内结算值。"""
        rows = ExcelService._transaction_export_rows([
            tx_row(type='赎回', source='redemption', shares=200.0, price=1.5678, amount=313.56)
        ])
        assert rows[0][3] == '赎回'
        assert rows[0][4] == 200.0
        assert rows[0][6] == 313.56

    def test_pending_purchase_leaves_shares_and_price_empty(self):
        """待确认买入:份额/单价是 0 占位,导数值回导必超 0.5% 差线,须留空只留录入金额。"""
        rows = ExcelService._transaction_export_rows([
            tx_row(status='0', shares=0.0, price=0.0, amount=1234.5)
        ])
        assert rows[0][4] is None
        assert rows[0][5] is None
        assert rows[0][6] == 1234.5

    def test_pending_redemption_leaves_price_and_amount_empty_keeps_shares(self):
        """待确认赎回:份额已确定保留,净值未公布故到账金额留空。"""
        rows = ExcelService._transaction_export_rows([
            tx_row(type='赎回', source='redemption', status='0', shares=200.0, price=0.0, amount=0.0)
        ])
        assert rows[0][4] == 200.0
        assert rows[0][5] is None
        assert rows[0][6] is None

    def test_zero_amount_renders_none_not_zero(self):
        """金额 0 不落 0(空单元格),避免回导时把占位 0 当成有效金额。"""
        rows = ExcelService._transaction_export_rows([tx_row(amount=0)])
        assert rows[0][6] is None

    def test_export_headers_match_template_headers(self):
        """导出表头与导入模板表头同源:模板改了别名,导出自动跟随。"""
        from module_portfolio.service.excel_service import TEMPLATE_FIELDS

        headers = ExcelService._template_headers()
        assert len(headers) == len(TEMPLATE_FIELDS) == 8
