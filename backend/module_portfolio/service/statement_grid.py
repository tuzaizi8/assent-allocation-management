"""OCR 文本块还原成表格网格(纯函数,只依赖 statement_ocr 的数据结构)。

截图与扫描件没有结构化表格,OCR 只给「文本 + 四点坐标」。本模块把散块还原成行列网格:

1. 行聚类:按 y 中心分组,容差取行高中位数 * 0.6(字号越大行距越大);
2. 列聚类:以「块数最多的那一行」为种子切列区间,再按 x 区间重叠把每个块指派到列(两轮迭代)。
   用区间重叠而不是 x 中心:数值列常右对齐,中心与表头并不对齐,按中心聚类会把同一列劈成两列。
   表头行**以上**的行(标题/页眉)不参与列宽推断:那种横跨整行的长文本被指派到首列后会把首列撑到
   整行宽,把紧邻的第二列整列吞掉。

纯函数 + 确定性:同样输入必得同样的表,便于单测。
"""

from collections.abc import Sequence

from module_portfolio.service.statement_ocr import TextBox

# 行聚类容差 = 行高中位数 * 该比例(下限见 ROW_TOLERANCE_MIN,防止小字号行被误并)
ROW_TOLERANCE_RATIO = 0.6
ROW_TOLERANCE_MIN = 4.0
# 列区间的迭代轮数:一轮"指派→并区间"后再指派一次即可稳定
COLUMN_PASSES = 2


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def row_tolerance(boxes: Sequence[TextBox]) -> float:
    """行聚类容差(按行高中位数自适应)。"""
    heights = [box.height for box in boxes if box.height > 0]
    if not heights:
        return ROW_TOLERANCE_MIN
    return max(ROW_TOLERANCE_MIN, _median(heights) * ROW_TOLERANCE_RATIO)


def cluster_rows(boxes: Sequence[TextBox], tolerance: float | None = None) -> list[list[TextBox]]:
    """按 y 中心把文本框聚成行,行内按 x 升序。"""
    items = [box for box in boxes if box.text.strip()]
    if not items:
        return []
    tol = row_tolerance(items) if tolerance is None else tolerance
    rows: list[list[TextBox]] = []
    current: list[TextBox] = []
    current_sum = 0.0
    for box in sorted(items, key=lambda item: (item.y_center, item.x0)):
        if current and abs(box.y_center - current_sum / len(current)) > tol:
            rows.append(sorted(current, key=lambda item: item.x0))
            current = []
            current_sum = 0.0
        current.append(box)
        current_sum += box.y_center
    if current:
        rows.append(sorted(current, key=lambda item: item.x0))
    return rows


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def _assign(box: TextBox, regions: list[tuple[float, float]]) -> int:
    """把一个文本块指派到列:优先取 x 区间重叠最大的列,全无重叠则取中心最近的列。"""
    best = 0
    best_overlap = 0.0
    for idx, (start, end) in enumerate(regions):
        overlap = _overlap(box.x0, box.x1, start, end)
        if overlap > best_overlap:
            best_overlap = overlap
            best = idx
    if best_overlap > 0:
        return best
    return min(range(len(regions)), key=lambda idx: abs(box.x_center - (regions[idx][0] + regions[idx][1]) / 2))


def _merge_regions(regions: list[tuple[float, float]], buckets: list[list[TextBox]]) -> list[tuple[float, float]]:
    """把每列的区间扩到该列所有块的外包(只扩不缩,避免相邻列互相吞并)。"""
    merged: list[tuple[float, float]] = []
    for idx, (start, end) in enumerate(regions):
        if buckets[idx]:
            merged.append((min(start, *(box.x0 for box in buckets[idx])), max(end, *(box.x1 for box in buckets[idx]))))
        else:
            merged.append((start, end))
    return merged


def build_table(
    boxes: Sequence[TextBox], tolerance: float | None = None
) -> tuple[tuple[tuple[str, ...], ...], tuple[int, ...], float]:
    """把文本块还原成表格网格。

    返回 (rows, row_refs, confidence):
    - rows:每行等宽的单元格文本(空单元格为 '')
    - row_refs:每行对应的来源行号(按 y 升序,1 起)
    - confidence:全表平均置信度
    """
    rows = cluster_rows(boxes, tolerance)
    if not rows:
        return (), (), 0.0

    # 种子行取块数最多的一行(表格类截图通常是表头行);表头行**以上**的标题/页眉不参与列宽推断——
    # 它们常是横跨整行的长文本(如「蚂蚁基金 基金交易明细」),指派到首列会把首列撑到整行宽,
    # 紧邻的第二列整列被吞掉(实测踩到:基金代码与确认份额并成一格)。
    seed_index = max(range(len(rows)), key=lambda index: len(rows[index]))
    table_rows = rows[seed_index:]
    regions: list[tuple[float, float]] = [(box.x0, box.x1) for box in rows[seed_index]]
    for _ in range(COLUMN_PASSES):
        buckets: list[list[TextBox]] = [[] for _ in regions]
        for row in table_rows:
            for box in row:
                buckets[_assign(box, regions)].append(box)
        regions = _merge_regions(regions, buckets)

    grid: list[tuple[str, ...]] = []
    refs: list[int] = []
    row_scores: list[float] = []
    for ref, row in enumerate(rows, start=1):
        buckets = [[] for _ in regions]
        for box in row:
            buckets[_assign(box, regions)].append(box)
        grid.append(
            tuple(
                ' '.join(box.text.strip() for box in sorted(cells, key=lambda item: item.x0)).strip()
                for cells in buckets
            )
        )
        refs.append(ref)
        row_scores.extend(box.score for box in row if box.score is not None)

    confidence = sum(row_scores) / len(row_scores) if row_scores else 1.0
    return tuple(grid), tuple(refs), round(confidence, 4)
