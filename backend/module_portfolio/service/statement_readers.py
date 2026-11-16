"""交易明细多格式读取层:魔数嗅探 + Excel / PDF / 图片三类 reader。

把任意来源统一成 DocumentContent(文本行 + 表格 + 解析层 + 置信度),字段怎么认由
statement_adapters 的 YAML 适配器决定:本层不认平台、不做守恒校验。

- Excel:openpyxl 读成整表,交给适配器按表头定位;
- PDF:pdfplumber 抽文本与表格;某页有效字符过少(扫描件/图片页)才渲染位图走 OCR;
- 截图:直接走 OCR;
- OCR 结果经 statement_grid 坐标聚类还原成网格;
- 可选依赖(pdfplumber / Pillow / rapidocr / numpy)缺失时转业务错误(见 _require),不让 500 冒出去。

全部同步阻塞,统一经 read_document_services(asyncio.to_thread) 调用。
"""

import asyncio
import importlib.util
import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from exceptions.exceptions import ServiceWarning
from module_portfolio.service.statement_grid import build_table
from module_portfolio.service.statement_ocr import OcrEngine, get_ocr_engine
from utils.log import logger

KIND_EXCEL = 'excel'
KIND_PDF = 'pdf'
KIND_IMAGE = 'image'

MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
MIME_PDF = 'application/pdf'
MIME_PNG = 'image/png'
MIME_JPEG = 'image/jpeg'

LAYER_TEXT = 'text'
LAYER_OCR = 'ocr'

# PDF 不设页数上限(2026-09-17 按要求删掉 MAX_PAGES):多少页都收,代价是耗时与内存随页数涨——
# 实测 78 页 0.9MB 文本层 PDF:读取 41.1s、峰值内存 525MB(慢在逐页 extract_tables,0.53s/页),
# 扫描件按页 OCR 更慢,上千页有 OOM 风险;重活交给使用者自行判断。
MAX_SHEET_ROWS = 3000
MAX_IMAGE_SHORT_SIDE = 2400
# 一页 PDF 的有效字符数低于该值即认定不是文本层(扫描件/纯图片页),转 OCR
MIN_TEXT_CHARS_PER_PAGE = 30
OCR_RENDER_DPI = 200

# 魔数:不信扩展名。现状对 .xls 是「放行 → 读不了 → 500」,这里提前明确拒绝。
_PDF_MAGIC = b'%PDF-'
_ZIP_MAGIC = b'PK\x03\x04'
_XLS_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
_JPEG_MAGIC = b'\xff\xd8\xff'

# 可选依赖:装了才支持对应格式。(自检项,便于环境缺包时一眼看出;安装提示里的名字是 pip 包名)
_OPTIONAL_DEPS = (
    ('Excel 读取', 'openpyxl', 'openpyxl'),
    ('PDF 文本层', 'pdfplumber', 'pdfplumber'),
    ('截图解码', 'PIL', 'Pillow'),
    ('OCR 推理', 'rapidocr', 'rapidocr'),
    ('OCR 数组运算', 'numpy', 'numpy'),
)
_INSTALL_HINT = '请在实际运行后端的那个 Python 环境里执行 pip install -e .'


def _require(module: str, capability: str, package: str | None = None) -> Any:
    """惰性导入可选依赖;缺包时抛业务错误(带包名与安装提示),不让 ModuleNotFoundError 冒成 500。"""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        name = package or module
        raise ServiceWarning(
            message=f'{capability}需要 {name}，当前运行环境缺少该依赖：{exc}（{_INSTALL_HINT}）'
        ) from exc


@dataclass(frozen=True)
class DocumentTable:
    """页内的一张表:等宽单元格 + 每行的来源行号(Excel 行号 / PDF 表内行序 / OCR 行序)。"""

    page_no: int
    rows: tuple[tuple[str, ...], ...]
    row_refs: tuple[int, ...]
    layer: str = LAYER_TEXT
    confidence: float = 1.0


@dataclass(frozen=True)
class DocumentPage:
    """一页内容:文本行(供平台指纹与表头定位)+ 表格集合。"""

    page_no: int
    lines: tuple[str, ...]
    tables: tuple[DocumentTable, ...] = ()
    layer: str = LAYER_TEXT
    confidence: float = 1.0
    note: str = ''


@dataclass(frozen=True)
class DocumentContent:
    """一份文件的统一形态。"""

    kind: str
    mime: str
    pages: tuple[DocumentPage, ...]
    ocr_used: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def lines(self) -> tuple[str, ...]:
        """全文文本行(平台指纹识别用)。"""
        return tuple(line for page in self.pages for line in page.lines)

    @property
    def tables(self) -> tuple[DocumentTable, ...]:
        """全文表格集合(按页序)。"""
        return tuple(table for page in self.pages for table in page.tables)


def _clean_cell(value: Any) -> str:
    """单元格文本归一:换行/回车→空格,连续空白压缩,首尾去空。"""
    if value is None:
        return ''
    text = str(value).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def _clean_lines(text: str) -> tuple[str, ...]:
    return tuple(line for line in (_clean_cell(raw) for raw in text.splitlines()) if line)


def _zip_has_xl(content: bytes) -> bool:
    """ZIP 容器里是否有 xl/ 目录(判断是不是 xlsx)。"""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return any(name.startswith('xl/') for name in archive.namelist())
    except zipfile.BadZipFile:
        return False


def sniff_kind(content: bytes, filename: str = '') -> tuple[str, str]:
    """按魔数判断文件类型,返回 (kind, mime);认不出抛业务错误。"""
    if not content:
        raise ServiceWarning(message='文件内容为空，请重新选择文件')
    if content.startswith(_PDF_MAGIC):
        return KIND_PDF, MIME_PDF
    if content.startswith(_XLS_MAGIC):
        raise ServiceWarning(message='暂不支持 Excel 97-2003 的 .xls（二进制格式），请另存为 .xlsx 后重试')
    if content.startswith(_ZIP_MAGIC):
        if _zip_has_xl(content):
            return KIND_EXCEL, MIME_XLSX
        raise ServiceWarning(message='这个压缩包/Office 文件里没有 Excel 工作表（xl/），请上传 .xlsx 交易明细')
    if content.startswith(_PNG_MAGIC):
        return KIND_IMAGE, MIME_PNG
    if content.startswith(_JPEG_MAGIC):
        return KIND_IMAGE, MIME_JPEG
    suffix = f'（文件名 {filename}）' if filename else ''
    raise ServiceWarning(message=f'无法识别的文件格式{suffix}：支持 .xlsx 交易明细、PDF 对账单、PNG/JPEG 截图')


def _read_excel(content: bytes) -> DocumentContent:
    """Excel:整表读成一张表,空行不产出行号也不产出数据。"""
    openpyxl = _require('openpyxl', 'Excel 解析')

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:
        raise ServiceWarning(message=f'Excel 文件无法打开：{exc}') from exc

    pages: list[DocumentPage] = []
    warnings: list[str] = []
    try:
        for sheet_no, sheet in enumerate(workbook.worksheets, start=1):
            rows: list[tuple[str, ...]] = []
            refs: list[int] = []
            lines: list[str] = []
            for row_no, raw_row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if row_no > MAX_SHEET_ROWS:
                    warnings.append(f'工作表「{sheet.title}」超过 {MAX_SHEET_ROWS} 行，已截断')
                    break
                cells = tuple(_clean_cell(value) for value in raw_row)
                if not any(cells):
                    continue
                rows.append(cells)
                refs.append(row_no)
                lines.append(' '.join(cell for cell in cells if cell))
            if not rows:
                continue
            table = DocumentTable(page_no=sheet_no, rows=tuple(rows), row_refs=tuple(refs), layer=LAYER_TEXT)
            pages.append(
                DocumentPage(
                    page_no=sheet_no,
                    lines=(_clean_cell(sheet.title), *lines),
                    tables=(table,),
                    layer=LAYER_TEXT,
                )
            )
    finally:
        workbook.close()

    if not pages:
        raise ServiceWarning(message='Excel 里没有可读的数据行，请确认导出的是交易明细')
    return DocumentContent(kind=KIND_EXCEL, mime=MIME_XLSX, pages=tuple(pages), warnings=tuple(warnings))


def _limit_image(image: Any) -> Any:
    """短边超限时等比缩放(OCR 对大图既慢又无收益)。"""
    width, height = image.size
    short_side = min(width, height)
    if short_side <= MAX_IMAGE_SHORT_SIDE or short_side == 0:
        return image
    ratio = MAX_IMAGE_SHORT_SIDE / short_side
    return image.resize((max(1, int(width * ratio)), max(1, int(height * ratio))))


def _ocr_image(image: Any, page_no: int, engine: OcrEngine | None, warnings: list[str]) -> list:
    """对一张位图跑 OCR;失败降级为警告(不影响同文件里的纯文本页)。"""
    try:
        limited = _limit_image(image)
        buffer = io.BytesIO()
        limited.save(buffer, format='PNG')
        return (engine or get_ocr_engine()).recognize(buffer.getvalue())
    except ServiceWarning as exc:
        warnings.append(f'第 {page_no} 页 OCR 失败：{exc.message or exc}')
    except Exception as exc:
        warnings.append(f'第 {page_no} 页 OCR 失败：{exc}')
    return []


def _read_pdf_page(page: Any, page_no: int, engine: OcrEngine | None, warnings: list[str]) -> tuple[DocumentPage, bool]:
    """读一页 PDF:有效字符够走文本层,不够则渲染位图走 OCR。返回 (页对象, 是否用了 OCR)。"""
    text = ''
    try:
        text = page.extract_text() or ''
    except Exception as exc:
        warnings.append(f'第 {page_no} 页文本层抽取失败：{exc}')

    if len(re.sub(r'\s', '', text)) >= MIN_TEXT_CHARS_PER_PAGE:
        tables: list[DocumentTable] = []
        try:
            for raw_table in page.extract_tables() or []:
                rows = tuple(tuple(_clean_cell(cell) for cell in raw_row) for raw_row in raw_table)
                rows = tuple(row for row in rows if any(row))
                if rows:
                    tables.append(
                        DocumentTable(
                            page_no=page_no,
                            rows=rows,
                            row_refs=tuple(range(1, len(rows) + 1)),
                            layer=LAYER_TEXT,
                        )
                    )
        except Exception as exc:
            warnings.append(f'第 {page_no} 页表格抽取失败：{exc}')
        return DocumentPage(page_no=page_no, lines=_clean_lines(text), tables=tuple(tables), layer=LAYER_TEXT), False

    try:
        image = page.to_image(resolution=OCR_RENDER_DPI).original
    except Exception as exc:
        warnings.append(f'第 {page_no} 页位图渲染失败，无法 OCR：{exc}')
        return DocumentPage(page_no=page_no, lines=(), layer=LAYER_OCR, note='位图渲染失败'), True

    boxes = _ocr_image(image, page_no, engine, warnings)
    if not boxes:
        return DocumentPage(page_no=page_no, lines=(), layer=LAYER_OCR, note='未识别到文字'), True

    rows, refs, confidence = build_table(boxes)
    table = DocumentTable(page_no=page_no, rows=rows, row_refs=refs, layer=LAYER_OCR, confidence=confidence)
    return (
        DocumentPage(
            page_no=page_no,
            lines=tuple(' '.join(cell for cell in row) for row in rows),
            tables=(table,),
            layer=LAYER_OCR,
            confidence=confidence,
        ),
        True,
    )


def _read_pdf(content: bytes, engine: OcrEngine | None) -> DocumentContent:
    """PDF:逐页判文本层,文本层不够的页才 OCR。"""
    pdfplumber = _require('pdfplumber', 'PDF 解析')

    try:
        pdf = pdfplumber.open(io.BytesIO(content))
    except Exception as exc:
        raise ServiceWarning(message=f'PDF 文件无法打开：{exc}') from exc

    pages: list[DocumentPage] = []
    warnings: list[str] = []
    ocr_used = False
    try:
        for page_no, page in enumerate(pdf.pages, start=1):
            page_content, page_ocr = _read_pdf_page(page, page_no, engine, warnings)
            pages.append(page_content)
            ocr_used = ocr_used or page_ocr
    finally:
        pdf.close()

    if not any(page.lines for page in pages):
        raise ServiceWarning(message='PDF 里没有可读文字（可能是加密或纯图片文件），请换一份明细或改用截图')
    return DocumentContent(
        kind=KIND_PDF,
        mime=MIME_PDF,
        pages=tuple(pages),
        ocr_used=ocr_used,
        warnings=tuple(warnings),
    )


def _read_image(content: bytes, mime: str, engine: OcrEngine | None) -> DocumentContent:
    """截图:直接 OCR + 坐标聚类还原表格。"""
    Image = _require('PIL.Image', '截图解析', 'Pillow')

    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except Exception as exc:
        raise ServiceWarning(message=f'图片无法打开：{exc}') from exc

    warnings: list[str] = []
    boxes = _ocr_image(image, 1, engine, warnings)
    if not boxes:
        # 截图没有「别的页」可退:把 OCR 失败的真因(引擎不可用/依赖缺失)带出来,别只报「没识别到文字」
        detail = f'（{warnings[-1]}）' if warnings else ''
        raise ServiceWarning(message=f'截图没有识别出文字{detail}，请换更清晰的截图，或改用 Excel/PDF 明细')

    rows, refs, confidence = build_table(boxes)
    table = DocumentTable(page_no=1, rows=rows, row_refs=refs, layer=LAYER_OCR, confidence=confidence)
    page = DocumentPage(
        page_no=1,
        lines=tuple(' '.join(cell for cell in row) for row in rows),
        tables=(table,),
        layer=LAYER_OCR,
        confidence=confidence,
    )
    return DocumentContent(kind=KIND_IMAGE, mime=mime, pages=(page,), ocr_used=True, warnings=tuple(warnings))


def read_document(content: bytes, filename: str = '', ocr_engine: OcrEngine | None = None) -> DocumentContent:
    """按魔数选择 reader(同步阻塞;调用侧用 read_document_services)。"""
    kind, mime = sniff_kind(content, filename)
    if kind == KIND_EXCEL:
        document = _read_excel(content)
    elif kind == KIND_PDF:
        document = _read_pdf(content, ocr_engine)
    else:
        document = _read_image(content, mime, ocr_engine)

    if document.ocr_used:
        logger.info(f'[导入] 命中 OCR 路径 文件={filename or kind} 类型={kind} 页数={len(document.pages)}')
    for warning in document.warnings:
        logger.warning(f'[导入] 解析告警 文件={filename or kind} | {warning}')
    return document


async def read_document_services(
    content: bytes, filename: str = '', ocr_engine: OcrEngine | None = None
) -> DocumentContent:
    """异步入口:openpyxl / pdfplumber / OCR 都是同步阻塞,统一丢线程池。"""
    return await asyncio.to_thread(read_document, content, filename, ocr_engine)


def _module_available(module: str) -> bool:
    """模块是否可导入:只查 spec,不真正 import(避免启动就载入 onnxruntime 这类重依赖)。"""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # 父包缺失,或 sys.modules 里被置为 None
        return False


def _check_optional_dependencies() -> None:
    """启动自检:把导入能力(Excel/PDF/截图/OCR)的就绪情况打一行日志,环境缺包一眼可见。"""
    ready: list[str] = []
    missing: list[str] = []
    for label, module, package in _OPTIONAL_DEPS:
        if _module_available(module):
            ready.append(label)
        else:
            missing.append(f'{label}({package})')
    if missing:
        logger.warning(
            f'[导入] 能力自检 | 就绪: {"、".join(ready) or "无"} | 缺失: {"、".join(missing)}'
            f' —— 缺失项会让对应格式导入直接失败,{_INSTALL_HINT}'
        )
    else:
        logger.info(f'[导入] 能力自检 | 就绪: {"、".join(ready)}')


_check_optional_dependencies()
