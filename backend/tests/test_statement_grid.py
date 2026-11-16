"""OCR 文本块 → 表格网格的坐标聚类单测(纯函数)。

对齐截图识别的真实形状:同一行的块 y 中心并不完全相等(OCR 框有抖动),
数值列常右对齐(中心与表头不对齐),所以列归属按「x 区间重叠」而不是 x 中心。
"""

from module_portfolio.service.statement_grid import build_table, cluster_rows, row_tolerance
from module_portfolio.service.statement_ocr import TextBox


def box(text: str, x0: float, y0: float, x1: float, y1: float, score: float = 1.0) -> TextBox:
    return TextBox(text=text, x0=x0, y0=y0, x1=x1, y1=y1, score=score)


class TestClusterRows:
    """行聚类:y 中心差在容差内算同一行,超过则分行。"""

    def test_same_row_when_y_jitter_within_tolerance(self):
        rows = cluster_rows([box('a', 0, 10, 20, 22), box('b', 30, 11, 50, 23)])
        assert len(rows) == 1
        assert [item.text for item in rows[0]] == ['a', 'b']

    def test_split_rows_when_far_apart(self):
        rows = cluster_rows([box('a', 0, 10, 20, 22), box('b', 0, 40, 20, 52)])
        assert len(rows) == 2

    def test_row_sorted_by_x(self):
        rows = cluster_rows([box('右', 80, 10, 100, 22), box('左', 0, 10, 20, 22)])
        assert [item.text for item in rows[0]] == ['左', '右']

    def test_blank_text_dropped(self):
        assert cluster_rows([box('   ', 0, 10, 20, 22)]) == []

    def test_tolerance_follows_font_height(self):
        assert row_tolerance([box('a', 0, 0, 10, 40)]) > row_tolerance([box('a', 0, 0, 10, 8)])


class TestBuildTable:
    """表格还原:等宽单元格、空单元格留空、右对齐数值不跑列。"""

    def test_table_shape_and_refs(self):
        boxes = [
            box('基金代码', 0, 0, 60, 14),
            box('确认份额', 100, 0, 160, 14),
            box('000001', 0, 20, 60, 34),
            box('78.7402', 100, 20, 160, 34),
        ]
        rows, refs, confidence = build_table(boxes)
        assert rows == (('基金代码', '确认份额'), ('000001', '78.7402'))
        assert refs == (1, 2)
        assert confidence == 1.0

    def test_right_aligned_number_stays_in_its_column(self):
        """数值右对齐(x 中心比表头偏右)仍归到表头那一列。"""
        boxes = [
            box('基金代码', 0, 0, 60, 14),
            box('确认金额', 200, 0, 260, 14),
            box('000001', 0, 20, 60, 34),
            box('1,234.56', 210, 20, 290, 34),
        ]
        rows, _, _ = build_table(boxes)
        assert rows[1] == ('000001', '1,234.56')

    def test_empty_cell_keeps_column_width(self):
        boxes = [
            box('订单号', 0, 0, 50, 14),
            box('基金代码', 100, 0, 150, 14),
            box('A001', 0, 20, 50, 34),
        ]
        rows, _, _ = build_table(boxes)
        assert rows[1] == ('A001', '')

    def test_wide_title_row_above_header_does_not_swallow_column(self):
        """表头以上的横跨整行标题不参与列宽推断(否则首列被撑宽,紧邻的第二列整列被吞)。"""
        boxes = [
            box('蚂蚁基金交易明细', 0, 0, 400, 14),
            box('确认份额', 0, 30, 60, 44),
            box('基金代码', 200, 30, 260, 44),
            box('78.7402', 0, 60, 60, 74),
            box('000001', 200, 60, 260, 74),
        ]
        rows, _, _ = build_table(boxes)
        assert rows[1] == ('确认份额', '基金代码')
        assert rows[2] == ('78.7402', '000001')

    def test_confidence_is_mean_of_scores(self):
        boxes = [
            box('基金代码', 0, 0, 60, 14, 0.9),
            box('000001', 0, 20, 60, 34, 0.7),
        ]
        _, _, confidence = build_table(boxes)
        assert confidence == 0.8

    def test_empty_input(self):
        assert build_table([]) == ((), (), 0.0)
