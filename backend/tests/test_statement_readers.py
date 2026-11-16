"""多格式读取层单测:魔数嗅探 + Excel/PDF/图片三类读取。

对齐真实踩到的坑:旧实现按扩展名放行 `.xls`,实际是「放行 → openpyxl 读不了 → 500」;
这里按内容魔数判断。OCR 用假引擎注入(不加载真模型),只验证读取层与网格还原的接线。
"""

import io
import sys

import openpyxl
import pytest
from PIL import Image

from exceptions.exceptions import ServiceWarning
from module_portfolio.service.statement_ocr import RapidOcrEngine, TextBox
from module_portfolio.service.statement_readers import (
    KIND_EXCEL,
    KIND_IMAGE,
    KIND_PDF,
    LAYER_OCR,
    LAYER_TEXT,
    MIME_PNG,
    MIME_XLSX,
    _module_available,
    read_document,
    sniff_kind,
)

# Excel 97-2003 的 OLE2 容器头(openpyxl 读不了)
OLE2_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'


class FakeOcrEngine:
    """假 OCR:返回预置文本框并记下调用次数(用于验证「文本层够用就不 OCR」)。"""

    def __init__(self, boxes: list[TextBox] | None = None) -> None:
        self.boxes = boxes or []
        self.calls = 0

    def recognize(self, image_bytes: bytes) -> list[TextBox]:
        self.calls += 1
        return list(self.boxes)


def table_boxes() -> list[TextBox]:
    """两列一行的表格文本框(表头 + 数据)。"""
    return [
        TextBox('订单号', 0, 10, 60, 24),
        TextBox('基金代码', 100, 10, 160, 24),
        TextBox('A001', 0, 30, 60, 44),
        TextBox('000001', 100, 30, 160, 44),
    ]


def make_xlsx(rows: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def make_png() -> bytes:
    image = Image.new('RGB', (200, 120), 'white')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def make_text_pdf(lines: list[str], pages: int = 1) -> bytes:
    """手工拼一份带文本层的最小 PDF(ASCII 即可触发文本层分支);pages>1 时所有页共用同一内容流。"""
    stream = '\n'.join(
        f'BT /F1 12 Tf 20 {200 - index * 16} Td ({line}) Tj ET' for index, line in enumerate(lines)
    )
    content_no = 3 + pages
    font_no = content_no + 1
    kids = ' '.join(f'{3 + index} 0 R' for index in range(pages))
    objects = [
        '<< /Type /Catalog /Pages 2 0 R >>',
        f'<< /Type /Pages /Kids [{kids}] /Count {pages} >>',
        *(
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 250] /Contents {content_no} 0 R'
            f' /Resources << /Font << /F1 {font_no} 0 R >> >> >>'
            for _ in range(pages)
        ),
        f'<< /Length {len(stream)} >>\nstream\n{stream}\nendstream',
        '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n{body}\nendobj\n'.encode('latin-1')
    xref_offset = len(out)
    out += f'xref\n0 {len(objects) + 1}\n'.encode('latin-1')
    out += b'0000000000 65535 f \n'
    for offset in offsets:
        out += f'{offset:010d} 00000 n \n'.encode('latin-1')
    out += f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n'.encode('latin-1')
    return bytes(out)


def make_image_pdf() -> bytes:
    """把图片塞进 PDF(Pillow 生成,没有文本层 → 必须走 OCR)。"""
    image = Image.new('RGB', (600, 200), 'white')
    buffer = io.BytesIO()
    image.save(buffer, format='PDF')
    return buffer.getvalue()


class TestSniffKind:
    """文件类型按内容判断,不信扩展名。"""

    def test_xlsx_named_as_xls_is_read_by_content(self):
        kind, mime = sniff_kind(make_xlsx([['基金代码']]), '明细.xls')
        assert (kind, mime) == (KIND_EXCEL, MIME_XLSX)

    def test_png_named_as_pdf_is_read_by_content(self):
        kind, mime = sniff_kind(make_png(), '截图.pdf')
        assert (kind, mime) == (KIND_IMAGE, MIME_PNG)

    def test_legacy_xls_rejected_with_business_error(self):
        with pytest.raises(ServiceWarning) as excinfo:
            sniff_kind(OLE2_MAGIC + b'\x00' * 32, '明细.xls')
        assert '.xls' in str(excinfo.value)

    def test_unknown_format_rejected(self):
        with pytest.raises(ServiceWarning):
            sniff_kind(b'hello world', 'note.txt')

    def test_empty_content_rejected(self):
        with pytest.raises(ServiceWarning):
            sniff_kind(b'', 'empty.xlsx')


class TestExcelReader:
    """Excel:整表读成一张表,空行跳过但保留原始行号。"""

    def test_rows_and_row_refs(self):
        content = make_xlsx([['标题行'], ['基金代码', '确认份额'], ['000001', '78.7402'], [None, None], ['110011', '10.5']])
        document = read_document(content, 'any.txt')
        assert document.kind == KIND_EXCEL
        table = document.tables[0]
        assert table.rows[0][0] == '标题行'
        assert table.row_refs == (1, 2, 3, 5)
        assert table.layer == LAYER_TEXT
        assert document.ocr_used is False

    def test_sheet_title_prefixed_into_lines(self):
        document = read_document(make_xlsx([['基金代码']]), 'x.xlsx')
        assert document.pages[0].lines[0] == 'Sheet'

    def test_empty_workbook_rejected(self):
        with pytest.raises(ServiceWarning):
            read_document(make_xlsx([[None]]), 'empty.xlsx')


class TestPdfReader:
    """PDF:有效字符够走文本层,不够才渲染位图喂 OCR。"""

    def test_text_layer_page_does_not_call_ocr(self):
        engine = FakeOcrEngine(table_boxes())
        content = make_text_pdf(['ORDER NO', 'FUND CODE 000001', 'CONFIRM AMOUNT 100.00'])
        document = read_document(content, 'text.pdf', ocr_engine=engine)
        assert document.kind == KIND_PDF
        assert document.ocr_used is False
        assert engine.calls == 0
        assert document.pages[0].layer == LAYER_TEXT
        assert any('000001' in line for line in document.pages[0].lines)

    def test_image_page_falls_back_to_ocr(self):
        engine = FakeOcrEngine(table_boxes())
        document = read_document(make_image_pdf(), 'scan.pdf', ocr_engine=engine)
        assert document.ocr_used is True
        assert engine.calls == 1
        assert document.pages[0].layer == LAYER_OCR
        assert document.tables[0].rows[0] == ('订单号', '基金代码')

    def test_multi_page_pdf_has_no_page_cap(self):
        """不设页数上限:25 页也要能读(改前会报「PDF 共 25 页，超过单文件上限 20 页」)。"""
        engine = FakeOcrEngine(table_boxes())
        content = make_text_pdf(['ORDER NO', 'FUND CODE 000001', 'CONFIRM AMOUNT 100.00'], pages=25)
        document = read_document(content, 'big.pdf', ocr_engine=engine)
        assert len(document.pages) == 25
        assert all(page.layer == LAYER_TEXT for page in document.pages)
        assert engine.calls == 0  # 每页都有文本层,不该触发 OCR


class TestImageReader:
    """截图:直接 OCR + 坐标聚类还原表格。"""

    def test_png_uses_ocr_and_grid(self):
        engine = FakeOcrEngine(table_boxes())
        document = read_document(make_png(), 'shot.png', ocr_engine=engine)
        assert document.kind == KIND_IMAGE
        assert document.ocr_used is True
        assert document.tables[0].rows == (('订单号', '基金代码'), ('A001', '000001'))

    def test_no_text_recognized_rejected(self):
        with pytest.raises(ServiceWarning):
            read_document(make_png(), 'blank.png', ocr_engine=FakeOcrEngine([]))


class TestMissingOptionalDependencies:
    """缺可选依赖要给业务错误(前端 601 友好提示),不能让 ModuleNotFoundError 冒成 500。

    对齐真实踩过的坑:服务器用的 venv 里没装 Pillow,截图上传直接 500(MissingPIL)。
    """

    def test_missing_pillow_rejected_with_business_error(self, monkeypatch):
        png = make_png()  # 先造字节,再屏蔽 PIL(否则造字节本身就会失败)
        # 置 None 会让导入抛 ImportError;PIL.Image 也要挡(子模块已缓存时 import_module 会直接命中缓存)
        monkeypatch.setitem(sys.modules, 'PIL', None)
        monkeypatch.setitem(sys.modules, 'PIL.Image', None)
        with pytest.raises(ServiceWarning) as excinfo:
            read_document(png, 'shot.png', ocr_engine=FakeOcrEngine(table_boxes()))
        assert 'Pillow' in str(excinfo.value)

    def test_missing_pdfplumber_rejected_with_business_error(self, monkeypatch):
        content = make_text_pdf(['ORDER NO'])
        monkeypatch.setitem(sys.modules, 'pdfplumber', None)
        with pytest.raises(ServiceWarning) as excinfo:
            read_document(content, 'text.pdf')
        assert 'pdfplumber' in str(excinfo.value)

    def test_missing_numpy_in_ocr_rejected_with_business_error(self, monkeypatch):
        png = make_png()
        monkeypatch.setitem(sys.modules, 'numpy', None)
        with pytest.raises(ServiceWarning) as excinfo:
            RapidOcrEngine().recognize(png)
        assert 'numpy' in str(excinfo.value)


class TestCapabilitySelfCheck:
    """启动自检只查 spec,不真正 import(避免启动就载入 onnxruntime 这类重依赖)。"""

    def test_probe_by_spec(self):
        assert _module_available('PIL') is True
        assert _module_available('definitely_not_an_installed_module_xyz') is False
