"""Excel 业务 Service(业务逻辑层):持仓导出 + 交易导入模板生成。

两个方向都用 openpyxl(同步阻塞,经 asyncio.to_thread 包裹)。交易明细的**解析**导入
(Excel / PDF / 截图 + 平台适配 YAML + 分级校验)在 statement_import_service(编排)、
statement_readers(多格式读取)、statement_adapters(平台适配)与 statement_validators(校验)。
"""

import asyncio
import io

from module_portfolio.service.statement_adapters import ADAPTERS, DEFAULT_ADAPTER_KEY

# 导入模板的列顺序:按用户填写习惯排(日期/代码/名称在前,份额/净值/金额/手续费收尾)。
# 列序不影响解析——适配器按**列名**认列,加列挪列都不会错位
TEMPLATE_FIELDS = ('date', 'fundCode', 'fundName', 'type', 'shares', 'unitPrice', 'amount', 'fee')
# 说明行占前 4 行,第 5 行留白,表头落在第 6 行。说明必须写在表头**之上**:
# 解析时只从表头行之后取数据行(见 statement_adapters._extract_from_table 的 start),
# 而表头行因命中 8 列,在 _locate_header 的全表评分里必然赢过任何说明行
TEMPLATE_NOTE_ROWS = 4
TEMPLATE_HEADER_ROW = TEMPLATE_NOTE_ROWS + 2
# 这两列必须整列设成文本格式:基金代码是 6 位(数值格式会吃掉前导 0,校验会判「不是 6 位数字」),
# 日期列避免被 Excel 转成序列号——读取侧 _clean_cell 只做 str(),真日期单元格会读成
# '2026-09-25 00:00:00'(故 generic.yaml 也补了带秒的日期格式)
TEMPLATE_TEXT_FIELDS = ('date', 'fundCode')


class ExcelService:
    """持仓 Excel 导出服务。"""

    @classmethod
    def _export_portfolio_sync(cls, positions: list[dict]) -> bytes:
        """导出持仓明细到 Excel(同步阻塞,调用侧 to_thread)。"""
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = '持仓明细'
        headers = [
            '基金代码', '基金名称', '基金类型', '持有份额', '持仓成本', '平均成本',
            '当前市值', '持有收益', '持有收益率', '状态',
        ]
        ws.append(headers)
        for pos in positions:
            ws.append([
                pos.get('fundCode', ''),
                pos.get('fundName', ''),
                pos.get('fundType', ''),
                pos.get('totalShares', 0),
                pos.get('totalCost', 0),
                pos.get('avgCostPrice', 0),
                pos.get('currentValue', 0),
                pos.get('profit', 0),
                f"{pos.get('profitRate', 0):.2f}%",
                pos.get('status', ''),
            ])
        for col in range(1, len(headers) + 1):
            ws.column_dimensions[chr(64 + col)].width = 15
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()

    @classmethod
    async def export_portfolio_services(cls, positions: list[dict]) -> bytes:
        """导出持仓数据(接收驼峰契约的持仓明细列表)。"""
        return await asyncio.to_thread(cls._export_portfolio_sync, positions)

    # ---------- 交易导入模板 ----------

    @staticmethod
    def _template_headers() -> list[str]:
        """模板表头 = 兜底适配器(generic)每个字段的**首个别名**。

        刻意从适配器配置生成、不写死字面量:模板与解析器同源,改了 generic.yaml 的别名,
        模板自动跟着变;tests/test_statement_import_template.py 反向锁住「表头能被映射回全部字段」。
        """
        aliases = ADAPTERS[DEFAULT_ADAPTER_KEY].field_aliases or {}
        return [aliases[field][0] for field in TEMPLATE_FIELDS]

    @classmethod
    def _import_template_sync(cls) -> bytes:
        """生成交易记录导入模板(同步阻塞,调用侧 to_thread)。"""
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        headers = cls._template_headers()
        notes = (
            '交易记录导入模板:按本表填写后,到「交易导入」页上传;系统先解析预览,确认后才入库。示例行请删除。',
            '必填:确认日期、基金代码、交易类型;买入与赎回都建议填「确认份额 + 确认净值」,'
            '净值未公布时可只填确认金额。',
            '格式:基金代码必须 6 位数字(本列已设文本格式,防前导 0 被吃掉);日期写成 2026-09-25;'
            '交易类型填「买入」或「赎回」,分红行填「红利再投」或「现金分红」。',
            '红线:确认金额与「确认份额 × 确认净值」偏差超过 0.5%该行报错;'
            '赎回必须填确认份额。',
        )
        # 示例两行内部自洽(份额 × 净值 = 金额),用户照它对齐格式后删掉;日期写成字符串,别让 Excel 转成序列号
        samples = (
            ('2026-01-05', '005827', '易方达蓝筹精选混合', '买入', 1000.00, 1.2345, 1234.50, 0.00),
            ('2026-06-18', '005827', '易方达蓝筹精选混合', '赎回', 200.00, 1.5678, 313.56, 0.00),
        )
        widths = (12, 12, 22, 10, 12, 12, 14, 10)

        wb = Workbook()
        ws = wb.active
        ws.title = '交易记录'
        for note in notes:
            ws.append([note])
        ws.append([])
        ws.append(list(headers))
        for row in samples:
            ws.append(list(row))

        # 说明行跨列合并:只占 A 列会被列宽截断,合并后一眼能读全
        for row_no in range(1, TEMPLATE_NOTE_ROWS + 1):
            ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=len(headers))
        for cell in ws[TEMPLATE_HEADER_ROW]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill('solid', fgColor='F2F2F2')
            cell.alignment = Alignment(horizontal='center')
        ws.freeze_panes = ws.cell(row=TEMPLATE_HEADER_ROW + 1, column=1).coordinate
        for index, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(index)].width = width
            # 文本格式只从表头行往下设:说明行是合并单元格,不去碰它
            if TEMPLATE_FIELDS[index - 1] in TEMPLATE_TEXT_FIELDS:
                for row_no in range(TEMPLATE_HEADER_ROW, ws.max_row + 1):
                    ws.cell(row=row_no, column=index).number_format = '@'

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()

    @classmethod
    async def export_import_template_services(cls) -> bytes:
        """生成交易记录导入模板(表头与解析器同源,供用户自行填写)。"""
        return await asyncio.to_thread(cls._import_template_sync)

    # ---------- 交易记录导出(与导入模板同列形,可回导) ----------

    @staticmethod
    def _transaction_export_rows(rows: list[dict]) -> list[list]:
        """交易记录(流水 union 行形)→ 模板 8 列(纯函数,可单测)。

        回导校验是「确认金额 vs 份额×净值 偏差 0.5%」:待确认行(status='0')的
        份额/单价是 0 占位、待确认赎回的到账金额未定,导成数值会必然超差,
        故按模板说明的口径留空——买入保留录入金额、赎回保留确认份额,
        回导时由 resolve_target_nav 按当前净值重新换算。
        手续费在流水表没有对应列,恒导 0。
        """
        exported: list[list] = []
        for row in rows:
            pending = row.get('status') == '0'
            shares = float(row.get('shares') or 0)
            price = float(row.get('price') or 0)
            amount = float(row.get('amount') or 0)
            exported.append([
                row.get('date') or '',
                row.get('fund_code') or '',
                row.get('fund_name') or '',
                row.get('type') or '',
                # 份额:待确认买入是 0 占位(数值未定),待确认赎回份额已确定保留
                None if shares <= 0 else shares,
                None if pending or price <= 0 else price,
                None if pending and row.get('type') == '赎回' else (amount or None),
                0,
            ])
        return exported

    @classmethod
    def _export_transactions_sync(cls, rows: list[dict]) -> bytes:
        """导出交易记录到 Excel(同步阻塞,调用侧 to_thread)。

        表头复用 _template_headers(与解析器同源):导出文件直接可在交易导入页回导,
        不带说明行——解析器按表头行定位,数据从表头下一行开始即可。
        """
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter

        headers = cls._template_headers()
        widths = (12, 12, 22, 10, 12, 12, 14, 10)

        wb = Workbook()
        ws = wb.active
        ws.title = '交易记录'
        ws.append(headers)
        for row in cls._transaction_export_rows(rows):
            ws.append(row)
        for index, field in enumerate(TEMPLATE_FIELDS, start=1):
            ws.column_dimensions[get_column_letter(index)].width = widths[index - 1]
            if field in TEMPLATE_TEXT_FIELDS:
                for row_no in range(1, ws.max_row + 1):
                    ws.cell(row=row_no, column=index).number_format = '@'
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()

    @classmethod
    async def export_transactions_services(cls, rows: list[dict]) -> bytes:
        """导出交易记录(接收流水 union 行形,按导入模板列形落 Excel)。"""
        return await asyncio.to_thread(cls._export_transactions_sync, rows)
