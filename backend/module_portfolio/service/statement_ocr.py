"""OCR 抽象层:图片字节 → 文本块(文本 + 四点坐标 + 置信度)。

上层(statement_readers / statement_grid)只依赖 OcrEngine 协议,默认实现为 RapidOCR
(纯 ONNX,模型随包分发,无需 GPU 与联网;首次调用才构造引擎,常驻内存约 50~100MB)。
日后要换 PaddleOCR 或 VLM,只替换实现,不动上层。

本模块整体为同步阻塞,调用侧(reader)负责用 asyncio.to_thread 包裹。
"""

import io
from dataclasses import dataclass
from typing import Any, Protocol

from exceptions.exceptions import ServiceWarning


@dataclass(frozen=True)
class TextBox:
    """一个文本块:内容 + 外接矩形 + 置信度(坐标原点在图片左上角,单位像素)。"""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = 1.0

    @property
    def x_center(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def y_center(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def width(self) -> float:
        return abs(self.x1 - self.x0)

    @property
    def height(self) -> float:
        return abs(self.y1 - self.y0)


class OcrEngine(Protocol):
    """OCR 引擎边界:图片字节进,文本块列表出。"""

    def recognize(self, image_bytes: bytes) -> list[TextBox]:
        """识别一张图片,返回按识别顺序排列的文本块。"""
        ...


def _rect_from_points(points: Any) -> tuple[float, float, float, float]:
    """把四点四边形或矩形转成 (x0, y0, x1, y1)。"""
    coords = [(float(p[0]), float(p[1])) for p in points]
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return min(xs), min(ys), max(xs), max(ys)


def normalize_ocr_output(output: Any) -> list[TextBox]:
    """把不同版本 OCR 的输出统一成 TextBox 列表。

    兼容两种形状:rapidocr 3.x 的 RapidOCROutput(.boxes/.txts/.scores)
    与 2.x 的 (boxes, txts, scores) 三元组;空结果统一返回空列表。
    """
    if output is None:
        return []

    boxes = getattr(output, 'boxes', None)
    texts = getattr(output, 'txts', None)
    scores = getattr(output, 'scores', None)
    if boxes is None and texts is None and isinstance(output, (tuple, list)) and len(output) == 3:
        boxes, texts, scores = output

    if boxes is None or texts is None:
        return []

    texts = list(texts)
    scores = list(scores) if scores is not None else [1.0] * len(texts)
    result: list[TextBox] = []
    for idx, points in enumerate(boxes):
        text = str(texts[idx]).strip() if idx < len(texts) else ''
        if not text:
            continue
        x0, y0, x1, y1 = _rect_from_points(points)
        score = float(scores[idx]) if idx < len(scores) and scores[idx] is not None else 1.0
        result.append(TextBox(text=text, x0=x0, y0=y0, x1=x1, y1=y1, score=score))
    return result


class RapidOcrEngine:
    """RapidOCR 实现:懒加载单例引擎(首次 recognize 才载入模型)。"""

    def __init__(self) -> None:
        self._engine: Any = None

    def _load(self) -> Any:
        if self._engine is None:
            try:
                from rapidocr import RapidOCR

                self._engine = RapidOCR()
            except Exception as exc:  # 模型缺失/依赖损坏:降级为明确业务错误,不让 500
                raise ServiceWarning(message=f'OCR 引擎不可用，图片与扫描件无法解析：{exc}') from exc
        return self._engine

    def recognize(self, image_bytes: bytes) -> list[TextBox]:
        """识别图片字节(PNG/JPEG 均可)。"""
        try:
            import numpy as np
            from PIL import Image
        except ImportError as exc:  # 缺 Pillow/numpy:降级为明确业务错误,不让 ModuleNotFoundError 冒成 500
            raise ServiceWarning(
                message=f'截图与扫描件解析需要 Pillow 与 numpy，当前运行环境缺少该依赖：{exc}'
                f'（请在实际运行后端的那个 Python 环境里执行 pip install -e .）'
            ) from exc

        try:
            image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        except Exception as exc:
            raise ServiceWarning(message=f'图片无法解码，请确认是 PNG/JPEG 截图：{exc}') from exc

        engine = self._load()
        output = engine(np.asarray(image))
        return normalize_ocr_output(output)


_ENGINE: OcrEngine | None = None


def get_ocr_engine() -> OcrEngine:
    """取全局 OCR 引擎单例(懒构造:模型只在首次真正识别时载入)。"""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RapidOcrEngine()
    return _ENGINE
