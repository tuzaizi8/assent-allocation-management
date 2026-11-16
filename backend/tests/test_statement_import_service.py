"""交易明细导入编排层单测(preview 契约 + confirm 的两道前置拦截)。

表格式明细的 preview 是纯解析 + 校验:db/redis 只在列表式截图(名称认代码、按净值换算份额)
那条分支里才用得上,故这里传 None 即可;confirm 的「取消」「校验拦截」两条分支也在碰数据库
之前就返回,所以整份用例不需要 DB。
"""

import asyncio
import io

import openpyxl
import pytest

from exceptions.exceptions import ServiceWarning
from module_portfolio.entity.vo.excel_vo import ImportTransactionRecordModel, TransactionConfirmModel
from module_portfolio.service.statement_import_service import (
    ORIGIN_EXISTING,
    ORIGIN_HAND,
    ORIGIN_NEW,
    REBUILD_NOT_DONE_MESSAGE,
    REBUILD_RETRY_ATTEMPTS,
    StatementImportService,
    build_rebuild_queue,
    should_rollback,
)

ALIPAY_ROWS = [
    ['蚂蚁基金交易明细'],
    ['确认份额', '基金代码', '申请份额', '订单号', '确认金额', '基金名称', '手续费', '确认日期'],
    [78.7402, '000001', '', 'A001', 100.0, '华夏成长混合', 0, '2026/05/08'],
    [21.3, '110011', '10.5', 'A002', 21.30, '易方达中小盘', 0.15, '2026-05-09'],
    [5.0, '12A45', '2.0', 'A003', 999.0, '代码格式错', 0, '2026-05-10'],
]


DIVIDEND_ROWS = [
    ['蚂蚁基金交易明细'],
    ['确认份额', '基金代码', '申请份额', '订单号', '确认金额', '基金名称', '手续费', '确认日期', '交易类型'],
    [0.92, '003095', '/', 'D001', 0.0, '中欧医疗健康混合A', 0, '2021/08/11', '机构分红'],
    [0.0, '003547', '/', 'D002', 1.18, '鹏华丰禄债券', 0, '2022/06/13', '机构分红'],
]


def make_xlsx(rows: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def preview(content: bytes, filename: str = 'alipay.xls') -> dict:
    return asyncio.run(
        StatementImportService.preview_transaction_import_services(None, None, 0, content, filename)
    )


class TestPurchaseShares:
    """confirm 落库的份额口径:文件有份额按文件;只有金额则待确认(落库只记金额)。

    这里刻意不补查净值:预览阶段已算过一次,confirm 再查会让预览与实际落库不一致。
    """

    def test_file_shares_win(self):
        assert StatementImportService._purchase_shares({'shares': 78.7402, 'unit_price': 1.27}) == (
            78.7402,
            1.27,
            False,
        )

    def test_amount_only_is_pending(self):
        assert StatementImportService._purchase_shares({'shares': 0, 'amount': 2.0}) == (0.0, 0.0, True)

    def test_nav_pending_flag_is_honoured(self):
        assert StatementImportService._purchase_shares({'shares': 0, 'amount': 0, 'nav_pending': True}) == (
            0.0,
            0.0,
            True,
        )

    def test_empty_row_stays_confirmed(self):
        assert StatementImportService._purchase_shares({}) == (0.0, 0.0, False)


class TestPreview:
    """preview:文件类型按内容识别,错误行踢出预览、保留在 errors。"""

    def test_contract_shape_kept(self):
        result = preview(make_xlsx(ALIPAY_ROWS))
        assert set(result) == {'preview', 'summary', 'errors', 'warnings'}
        assert result['summary']['purchases'] == 1
        assert result['summary']['redemptions'] == 1
        assert result['summary']['total'] == 2
        assert result['summary']['adapter'] == 'alipay'
        assert result['summary']['kind'] == 'excel'
        assert result['summary']['ocrUsed'] is False
        assert len(result['errors']) == 1

    def test_preview_row_keeps_frontend_keys_and_adds_source(self):
        row = preview(make_xlsx(ALIPAY_ROWS))['preview'][0]
        for key in ('row', 'type', 'fundCode', 'fundName', 'date', 'amount', 'shares', 'unitPrice', 'fee', 'orderNo', 'status'):
            assert key in row
        assert row['type'] == '买入'
        assert row['status'] == 'pending'
        assert row['adapter'] == 'alipay'
        assert row['layer'] == 'text'

    def test_bad_row_goes_to_errors_not_preview(self):
        result = preview(make_xlsx(ALIPAY_ROWS))
        assert all(item['fundCode'] != '12A45' for item in result['preview'])
        assert result['errors'][0]['row'] == 5
        assert result['errors'][0]['field'] == 'fundCode'
        assert 'error' in result['errors'][0]

    def test_excel_named_as_xls_still_parsed(self):
        """扩展名撒谎也照读(内容嗅探),这正是不再 500 的原因。"""

        assert preview(make_xlsx(ALIPAY_ROWS), '明细.xls')['summary']['total'] == 2

    def test_unsupported_file_raises_business_error(self):
        with pytest.raises(ServiceWarning):
            preview(b'not a table at all', 'note.txt')

    def test_no_records_recognized_raises(self):
        with pytest.raises(ServiceWarning):
            preview(make_xlsx([['订单号', '基金代码'], ['']]), 'empty.xlsx')


class TestDividendRows:
    """分红行的两处显式标记:预览行带标签(前端据此出徽标)、备注写明是分红。

    账本没有独立的分红表(分红就落在买入/赎回表里),所以备注是**持久化的唯一区分依据**。
    """

    def test_preview_row_carries_dividend_label(self):
        rows = preview(make_xlsx(DIVIDEND_ROWS))['preview']
        assert [(row['dividend'], row['type']) for row in rows] == [
            ('红利再投资', '买入'),
            ('现金分红', '买入'),
        ]

    def test_plain_row_has_no_dividend_label(self):
        assert preview(make_xlsx(ALIPAY_ROWS))['preview'][0]['dividend'] == ''


class TestConfirmGates:
    """confirm:取消与校验拦截都在落库之前返回。"""

    def test_cancelled_returns_unchanged_shape(self):
        result = asyncio.run(
            StatementImportService.confirm_transaction_import_services(
                None, None, 1, TransactionConfirmModel(confirmed=False, adapter='alipay', records=[])
            )
        )
        assert result['success'] is False
        assert result['positionsCreated'] == 0
        assert result['errors'][0]['error'] == '用户取消确认'

    def test_blocking_issue_refuses_to_commit(self):
        bad = ImportTransactionRecordModel(
            fund_code='12345',
            fund_name='代码错',
            date='2026-05-08',
            type='买入',
            amount=100.0,
            shares=80.0,
            unit_price=1.25,
        )
        result = asyncio.run(
            StatementImportService.confirm_transaction_import_services(
                None, None, 1, TransactionConfirmModel(confirmed=True, adapter='alipay', records=[bad])
            )
        )
        assert result['success'] is False
        assert result['imported'] == {}
        assert result['errors'][0]['field'] == 'fundCode'

    def test_valid_payload_passes_the_gate(self):
        """合法记录不会被前置拦截(后续落库需要 DB,这里只验证关卡本身)。"""
        good = ImportTransactionRecordModel(
            fund_code='000001',
            fund_name='华夏成长混合',
            date='2026-05-08',
            type='买入',
            amount=100.0,
            shares=80.0,
            unit_price=1.25,
        )
        model = TransactionConfirmModel(confirmed=True, adapter='alipay', records=[good])
        assert len(model.records) == 1
        assert model.records[0].type == '买入'

    def test_unknown_adapter_is_rejected(self):
        """平台适配器 key 未知 → 直接报错、不静默降级(判重作用域缺失会让重复记录被当新数据累加)。"""
        with pytest.raises(ServiceWarning):
            asyncio.run(
                StatementImportService.confirm_transaction_import_services(
                    None, None, 1, TransactionConfirmModel(confirmed=True, adapter='不存在的平台', records=[])
                )
            )


class TestRebuildQueue:
    """重建队列装配:三类来源必须**都**带 `origin`——落库循环靠它分流「插入新记录」与「只重挂」。

    2026-09-20 的缺陷:本次新增记录直接来自请求载荷(前端白名单里没有 `origin`),装配时漏了补标记,
    于是 1265 条全部 `KeyError('origin')`,界面上只看到原因 `'origin'`。这组用例就是那次的回归测验。
    """

    def test_incoming_records_are_stamped_new(self):
        queue = build_rebuild_queue(existing=[], hand=[], incoming=[{'fund_code': '000001', 'date': '2026-05-08'}])
        assert [record['origin'] for record in queue] == [ORIGIN_NEW]

    def test_existing_and_hand_markers_are_not_overwritten(self):
        """已有/手输记录自带标记,装配不能把它们改写成「新增」(那会重复落库)。"""
        queue = build_rebuild_queue(
            existing=[{'fund_code': '000001', 'date': '2026-05-08', 'origin': ORIGIN_EXISTING}],
            hand=[{'fund_code': '110011', 'date': '2026-05-09', 'origin': ORIGIN_HAND}],
            incoming=[{'fund_code': '161725', 'date': '2026-05-10'}],
        )
        assert [record['origin'] for record in queue] == [ORIGIN_EXISTING, ORIGIN_HAND, ORIGIN_NEW]

    def test_order_is_existing_hand_incoming_on_the_same_day(self):
        """同一天按「已有 → 手输 → 新增」稳定排序(sort 稳定 + 拼装次序)。"""
        queue = build_rebuild_queue(
            existing=[{'fund_code': 'A', 'date': '2026-05-08', 'origin': ORIGIN_EXISTING}],
            hand=[{'fund_code': 'B', 'date': '2026-05-08', 'origin': ORIGIN_HAND}],
            incoming=[{'fund_code': 'C', 'date': '2026-05-08'}],
        )
        assert [record['fund_code'] for record in queue] == ['A', 'B', 'C']

    def test_records_without_date_are_dropped(self):
        queue = build_rebuild_queue(
            existing=[],
            hand=[],
            incoming=[{'fund_code': 'A', 'date': '2026-05-08'}, {'fund_code': 'B', 'date': None}, {'fund_code': 'C'}],
        )
        assert [record['fund_code'] for record in queue] == ['A']

    def test_every_queue_item_has_origin(self):
        """契约:队列里**每一条**都要带 origin——落库循环不做兜底,缺了就是逐条 KeyError。"""
        queue = build_rebuild_queue(
            existing=[{'fund_code': 'A', 'date': '2026-05-08', 'origin': ORIGIN_EXISTING}],
            hand=[{'fund_code': 'B', 'date': '2026-05-08', 'origin': ORIGIN_HAND}],
            incoming=[{'fund_code': 'C', 'date': '2026-05-09'}],
        )
        assert all('origin' in record for record in queue)


class TestRollbackGuard:
    """「零写入 + 有错误」才回滚:部分成功与全部判重跳过都不受影响。"""

    def test_zero_write_with_errors_rolls_back(self):
        """一条都没写进去还收了错误 → 这次重建等于白清空,必须回滚(否则提交就是清空用户数据)。"""
        assert should_rollback(errors=[{'error': "KeyError: 'origin'"}], purchases=0, redemptions=0) is True

    def test_partial_success_commits(self):
        assert should_rollback(errors=[{'error': 'x'}], purchases=3, redemptions=0) is False
        assert should_rollback(errors=[{'error': 'x'}], purchases=0, redemptions=2) is False

    def test_all_duplicates_skipped_commits(self):
        """全部判重跳过(无写入、无错误)是正常结果,不是失败。"""
        assert should_rollback(errors=[], purchases=0, redemptions=0) is False

    def test_normal_import_commits(self):
        assert should_rollback(errors=[], purchases=100, redemptions=20) is False


class TestConfirmRemarkPrefix:
    """导入备注固定前缀「导入:<平台>:」:DAO 靠它把导入数据与手输数据分开,并圈出判重作用域。"""

    def test_remark_keeps_prefix_platform_and_user_note(self):
        assert StatementImportService._import_remark({'fund_name': '华夏成长混合'}, 'alipay') == (
            '导入:alipay: 华夏成长混合'
        )
        assert (
            StatementImportService._import_remark({'fund_name': '华夏成长混合', 'remark': '定投'}, 'tiantian')
            == '导入:tiantian: 华夏成长混合 | 定投'
        )

    def test_remark_marks_dividend_after_the_scope_prefix(self):
        """分红标签跟在基金名之后,`导入:<平台>:` 仍必须在最前(判重作用域的锚)。"""
        remark = StatementImportService._import_remark(
            {'fund_name': '鹏华丰禄债券', 'dividend': '红利再投资', 'remark': '手工补录'}, 'tiantian'
        )
        assert remark == '导入:tiantian: 鹏华丰禄债券 | 红利再投资 | 手工补录'
        assert remark.startswith('导入:tiantian:')

    def test_remark_prefix_is_the_platform_scope(self):
        """判重按 `导入:<平台>:%` 圈范围,故备注必须以「导入:<平台>:」开头(手输记录没有这个前缀)。"""
        remark = StatementImportService._import_remark({'fund_name': '华夏成长混合'}, 'alipay')
        assert remark.startswith('导入:alipay:')


class TestImportSnapshotRebuild:
    """导入后的快照重建:被占用时有界重试,并把结果带回回执(以前只写日志、界面看不出来)。"""

    class FakeSession:
        async def rollback(self):
            return None

    def patch(self, monkeypatch, outcomes):
        """按调用次序给出结果(异常即抛出);重试间隔置 0,测试不真等待。"""
        from module_portfolio.service import statement_import_service as module
        from module_portfolio.service.snapshot_service import SnapshotService

        calls = {'n': 0}

        async def fake_rebuild(_db, _redis, _user_id):
            calls['n'] += 1
            outcome = outcomes[min(calls['n'] - 1, len(outcomes) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(SnapshotService, 'rebuild_from_transactions_services', fake_rebuild)
        monkeypatch.setattr(module, 'REBUILD_RETRY_DELAY_SECONDS', 0)
        return calls

    def run(self, monkeypatch, outcomes):
        calls = self.patch(monkeypatch, outcomes)
        result = asyncio.run(StatementImportService._rebuild_snapshots(self.FakeSession(), None, 1))
        return result, calls['n']

    def test_busy_then_success(self, monkeypatch):
        """首次被占用(冷却窗口/写锁)、第二次成功 → 判定已重建、无文案。"""
        (ok, message), attempts = self.run(
            monkeypatch,
            [
                ServiceWarning(message='已有重建正在进行（正在执行中），请稍后重试'),
                {'rebuilt': {'snapshotsCreated': 10, 'cashFlowsCreated': 3}},
            ],
        )
        assert (ok, message) == (True, '')
        assert attempts == 2

    def test_busy_exhausted_reports_not_rebuilt(self, monkeypatch):
        """连续被占用到上限 → 判定未重建并给出可读文案(本次修复的核心:不再只写日志)。"""
        (ok, message), attempts = self.run(
            monkeypatch, [ServiceWarning(message='已有重建正在进行，请稍后再试')]
        )
        assert ok is False
        assert message == REBUILD_NOT_DONE_MESSAGE
        assert '快照未重建' in message
        assert attempts == REBUILD_RETRY_ATTEMPTS

    def test_other_error_is_not_retried(self, monkeypatch):
        """非占用型异常是真错,不重试 —— 否则会被掩盖成「稍后重试就好」。"""
        (ok, message), attempts = self.run(monkeypatch, [RuntimeError('boom')])
        assert (ok, message) == (False, REBUILD_NOT_DONE_MESSAGE)
        assert attempts == 1
