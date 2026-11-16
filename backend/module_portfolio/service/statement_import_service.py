"""多格式交易明细导入编排:preview 与 confirm(支付宝 Excel / PDF / 截图通吃)。

- preview:读文件 → 选平台适配器 → 抽记录 → 分级校验 → 组装响应(不落库);
- confirm:落库前再校验一次(有 error 直接拒绝),然后沿用既有语义
  「删上次导入数据 → 并入原始手输 → 删持仓头表 → 按日期升序逐条重建 → 单事务提交」,
  成功后补一次快照全量重建(失败只告警,不影响导入结果)。

导入解析层与落库层分开:解析全部在 statement_readers / statement_adapters,本模块只管编排。
"""

import asyncio
from datetime import date

from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.exceptions import ServiceWarning
from module_fund.dao.fund_dao import FundDao
from module_fund.service.akshare_service import AkshareService
from module_portfolio.dao.position_dao import PositionDao
from module_portfolio.dao.purchase_record_dao import PurchaseRecordDao
from module_portfolio.dao.redemption_record_dao import RedemptionRecordDao
from module_portfolio.entity.do.position_do import (
    POSITION_STATUS_FULLY_REDEEMED,
    POSITION_STATUS_NORMAL,
    UserFundPosition,
)
from module_portfolio.entity.do.purchase_record_do import PurchaseRecord
from module_portfolio.entity.do.redemption_record_do import RedemptionRecord
from module_portfolio.entity.vo.excel_vo import TransactionConfirmModel
from module_portfolio.service.position_calc_util import (
    ORDER_CUTOFF_HOUR,
    ORDER_CUTOFF_MINUTES,
    order_confirm_date as shared_order_confirm_date,
    remaining_shares,
)
from module_portfolio.service.snapshot_service import SnapshotService
from module_portfolio.service.statement_adapters import MODE_LIST_ITEM, detect_adapter, extract_records, get_adapter
from module_portfolio.service.statement_fund_resolver import resolve_fund_codes
from module_portfolio.service.statement_import_merge import plan_import_merge
from module_portfolio.service.statement_readers import read_document_services
from module_portfolio.service.statement_validators import (
    DIRECTION_PURCHASE,
    DIRECTION_REDEMPTION,
    Issue,
    direction_of,
    validate_records,
)
from utils.log import logger

# 导入写入 remark 的固定前缀:DAO 靠它把「导入数据」与「手输数据」分开
IMPORT_REMARK_PREFIX = '导入:'

# 重建队列里一条记录的来源(决定「插入新记录」还是「重挂 position_id」,以及赎回判定阈值)
ORIGIN_NEW = 'new'            # 本次文件里判重后剩下的新记录 → 落库
ORIGIN_HAND = 'hand'          # 手工录入的记录 → 保留,重挂
ORIGIN_EXISTING = 'existing'  # 上次导入留下的记录 → 保留,重挂(2026-09-19 起不再清场)

# 原始(手输)交易的全额赎回判定阈值
ORIGINAL_FULL_REDEMPTION_TOLERANCE = 0.01
# 导入交易的全额赎回判定阈值(份额经文件换算有精度差,放宽)
IMPORTED_FULL_REDEMPTION_TOLERANCE = 0.5

# 导入落库后补的那次快照全量重建:被占用时(上一次重建还在跑)做有界重试。
# 重建实测 4~100 秒,占锁者通常就是上一次导入触发的重建;总等待上限远小于导入请求的超时余量。
REBUILD_RETRY_ATTEMPTS = 3
REBUILD_RETRY_DELAY_SECONDS = 20
# 两道闸(Redis 冷却键 / DB 事务级写锁)抛的都是这句话,用它区分「被占用」与真错
# 下单切分时刻与确认日换算都在 `position_calc_util`(15:00 线全项目只有一份):
# 列表式截图(支付宝/天天基金 App)给的是**下单时间**而非确认日,15:00 之后下的单要按
# **下一交易日**净值成交,与「表格类文件给的是确认日」对齐;手工录入走同一个常量。
ORDER_TIME_UNKNOWN_MESSAGE = (
    '未识别到下单时间，已按当日净值处理；'
    f'若该笔实际在 {ORDER_CUTOFF_HOUR}:00 之后下单，请手动改为下一交易日'
)

REBUILD_BUSY_MARKER = '已有重建正在进行'
# 未重建成功时随回执回到界面:以前这里只写一行日志,用户看到的是"导入成功但图不对"
REBUILD_NOT_DONE_MESSAGE = '记录已入库，但快照未重建：请到「快照管理」页点一次「重建快照」，否则收益曲线会停在旧份额上'


def build_rebuild_queue(*, existing: list[dict], hand: list[dict], incoming: list[dict]) -> list[dict]:
    """把三类记录拼成重建队列:已有 → 手输 → 本次新增(同一天的先后;list.sort 稳定保持该次序)。

    本次新增记录直接来自请求载荷(前端白名单里没有 `origin`),**必须在这里补上来源标记**——
    落库循环靠 `record['origin']` 分流「插入新记录」与「只重挂 position_id」。2026-09-20 的缺陷
    正是漏了这一步:1265 条新记录全部 `KeyError('origin')`,而错误被逐条吞掉、持仓头表又已在循环
    前清空,接口最后还报 success(见 99 对应小节)。
    """
    for record in incoming:
        record['origin'] = ORIGIN_NEW
    merged = [*existing, *hand, *incoming]
    merged = [record for record in merged if record.get('date')]
    merged.sort(key=lambda record: record['date'])
    return merged


def should_rollback(*, errors: list[dict], purchases: int, redemptions: int) -> bool:
    """一条新记录都没写进去却收到了错误 → 这次重建等于「白清空」,必须回滚而不是提交。

    全部判重跳过(无错误)不算失败;部分成功(有写入)照旧提交,逐条错误原样回给前端。
    """
    return bool(errors) and purchases == 0 and redemptions == 0


class StatementImportService:
    """交易明细多格式导入服务。"""

    @classmethod
    async def preview_transaction_import_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, content: bytes, filename: str = ''
    ) -> dict:
        """解析文件并给出预览(不写业务数据);仅列表式截图要查库认代码、查净值换算份额,
        其中净值未命中缓存时会回源并写 fund_nav_history(技术缓存,与手工录入同一条链路)。"""
        document = await read_document_services(content, filename)
        adapter = detect_adapter(document)
        records = extract_records(document, adapter)
        cutoff_warnings: list[Issue] = []
        if adapter.mode == MODE_LIST_ITEM:
            # 先按下单时刻定确认日,再拿确认日去换净值:顺序反了会拿当天的净值算 15:00 后的单子
            cutoff_warnings = cls._apply_order_cutoff(records)
            await resolve_fund_codes(query_db, user_id, records)
            await cls._apply_nav_shares(query_db, redis, records)
        if not records:
            raise ServiceWarning(
                message=f'没有从文件里识别出交易记录（平台适配：{adapter.name} / 模式：{adapter.mode}），请确认文件内容'
            )
        kept, errors, warnings = validate_records(records, tolerance=adapter.tolerance)
        # 时间未识别的告警按页行排序后并入,与校验层产出的告警同一形态
        warnings = sorted(warnings + cutoff_warnings, key=lambda item: (item.page, item.row))
        purchases = sum(1 for record in kept if direction_of(record['type']) == DIRECTION_PURCHASE)

        logger.info(
            f'[导入] 预览完成 文件={filename or document.kind} 适配器={adapter.key} 记录={len(kept)} '
            f'拦截={len(errors)} 告警={len(warnings)} OCR={document.ocr_used}'
        )
        return {
            'preview': [cls._to_preview_row(record) for record in kept],
            'summary': {
                'purchases': purchases,
                'redemptions': len(kept) - purchases,
                'total': len(kept),
                'warnings': len(warnings),
                # 以下为新增字段(前端可选用,不影响既有解析)
                'adapter': adapter.key,
                'adapterName': adapter.name,
                'mode': adapter.mode,
                'kind': document.kind,
                'ocrUsed': document.ocr_used,
                'parsed': len(records),
            },
            'errors': [cls._to_issue_row(issue) for issue in errors],
            'warnings': [cls._to_issue_row(issue) for issue in warnings],
        }

    @classmethod
    async def confirm_transaction_import_services(
        cls,
        query_db: AsyncSession,
        redis: aioredis.Redis,
        user_id: int,
        confirm_model: TransactionConfirmModel,
    ) -> dict:
        """确认导入:校验拦截 → 按平台累加合并重建持仓 → 重建快照。

        2026-09-19 起不再「清掉上次导入的数据」:库里已有的记录一律保留,新文件里与**本平台**
        已有记录重复的丢弃(多重集判重,见 `statement_import_merge`),只追加真正的新记录;
        其它平台的记录不受影响(同名基金按 fund_code 合并求和),手输记录始终保留。
        """
        if not confirm_model.confirmed:
            return {
                'success': False,
                'imported': {},
                'positionsCreated': 0,
                'errors': [{'error': '用户取消确认'}],
            }

        # 平台作用域来自预览回传的适配器 key(支付宝的 PDF 与截图是两个 key、同一平台)
        adapter = get_adapter(confirm_model.adapter)
        records = [record.model_dump() for record in confirm_model.records]
        _, blocking, _ = validate_records(records)
        if blocking:
            logger.warning(f'[导入] 确认被校验拦截 user_id={user_id} 问题={len(blocking)}')
            return {
                'success': False,
                'imported': {},
                'positionsCreated': 0,
                'errors': [cls._to_issue_row(issue) for issue in blocking],
            }

        try:
            positions_created, errors, imported_purchases, imported_redemptions, skipped = await cls._merge_and_rebuild(
                query_db, user_id, records, platform=adapter.platform
            )
            if should_rollback(errors=errors, purchases=imported_purchases, redemptions=imported_redemptions):
                # 一条都没写成功,却已经把持仓头表删了重建:提交等于把用户数据清空,必须回滚
                await query_db.rollback()
                logger.error(
                    f'[导入] 一条都没写成功,已回滚 user_id={user_id} 错误={len(errors)} '
                    f'首条={errors[0].get("error") if errors else ""}'
                )
                return {
                    'success': False,
                    'imported': {},
                    'positionsCreated': 0,
                    'errors': [
                        {'error': '本次导入一条都没写成功，已回滚（持仓与记录保持原样），原因见下面的明细'},
                        *errors,
                    ],
                }
            await query_db.commit()
            logger.info(
                f'[导入] 交易确认完成 user_id={user_id} 平台={adapter.platform} 建仓={positions_created} '
                f'买入={imported_purchases} 赎回={imported_redemptions} 跳过重复={skipped} 错误={len(errors)}'
            )
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[导入] 交易确认失败回滚 user_id={user_id} | {e}')
            raise e

        # 交易改了却不重建快照,曲线会停在旧份额上——结果随回执回到界面,不再"只写日志"
        snapshot_rebuilt, snapshot_rebuild_message = await cls._rebuild_snapshots(
            query_db, redis, user_id
        )

        return {
            'success': True,
            # skipped = 同平台判重丢弃的条数(已有记录保留,新文件里重复的不再写一遍)
            'imported': {'purchases': imported_purchases, 'redemptions': imported_redemptions, 'skipped': skipped},
            'positionsCreated': positions_created,
            'errors': errors,
            # 记录确实已入库(success 仍为 True),但快照可能没跟上——界面据此提示手动重建一次
            'snapshotRebuilt': snapshot_rebuilt,
            'snapshotRebuildMessage': snapshot_rebuild_message,
        }

    # ==================== 内部:落库 ====================

    @classmethod
    async def _merge_and_rebuild(
        cls, query_db: AsyncSession, user_id: int, records: list[dict], *, platform: str
    ) -> tuple[int, list[dict], int, int, int]:
        """按平台累加:同平台已有记录保留 + 判重后只追加新记录,再把三类记录一起重建成持仓。

        2026-09-19 起**不再清场**:库里已有的导入记录(本平台与其它平台)与手输记录全部保留,
        判重只决定「本次文件里的记录是否落库」(见 `statement_import_merge.plan_import_merge`)。
        持仓头表仍是全量重建,因此保留下来的记录都要重挂 position_id。
        返回 (建仓数, 逐条错误, 新增买入数, 新增赎回数, 判重丢弃数)。
        """
        positions_created = 0
        errors: list[dict] = []
        imported_purchases = 0
        imported_redemptions = 0

        user_positions = await PositionDao.get_all_positions(query_db, user_id)
        user_position_ids = [position.position_id for position in user_positions]

        # 已有导入记录:本平台的那批用于判重;全部平台的那批都要重挂(它们指向的持仓行会被重建)
        platform_existing = await cls._imported_rows(query_db, user_position_ids, f'{IMPORT_REMARK_PREFIX}{platform}:')
        keep_existing = await cls._imported_rows(query_db, user_position_ids, IMPORT_REMARK_PREFIX)
        hand_rows = await cls._hand_rows(query_db, user_position_ids)

        kept_records, skipped = plan_import_merge(records, platform_existing)

        merged = build_rebuild_queue(existing=keep_existing, hand=hand_rows, incoming=kept_records)

        # 持仓头表全量重建(原始记录的 position_id 已失效)
        await PositionDao.delete_all_positions_for_user(query_db, user_id)
        await query_db.flush()

        for record in merged:
            try:
                fund = await FundDao.get_fund_by_code(query_db, record['fund_code'])
                if not fund:
                    errors.append({'fund_code': record['fund_code'], 'error': f"基金 {record['fund_code']} 不存在，跳过"})
                    continue

                position = await PositionDao.get_active_position_by_fund(query_db, user_id, record['fund_code'])
                if not position:
                    position = await PositionDao.add_position_dao(
                        query_db,
                        UserFundPosition(
                            user_id=user_id, fund_code=record['fund_code'], status=POSITION_STATUS_NORMAL
                        ),
                    )
                    positions_created += 1

                if record['origin'] != ORIGIN_NEW:
                    await cls._relink_record(query_db, record, position)
                    continue

                tx_date = date.fromisoformat(record['date'])
                remark = cls._import_remark(record, platform)
                if direction_of(record['type']) == DIRECTION_PURCHASE:
                    shares, nav, pending = cls._purchase_shares(record)
                    await PurchaseRecordDao.add_purchase_record_dao(
                        query_db,
                        PurchaseRecord(
                            position_id=position.position_id,
                            user_id=user_id,
                            fund_code=position.fund_code,
                            shares=shares,
                            cost_price=nav,
                            purchase_date=tx_date,
                            status='0' if pending else '1',
                            amount=record.get('amount') or None,
                            remark=remark,
                        ),
                    )
                    imported_purchases += 1
                else:
                    await RedemptionRecordDao.add_redemption_record_dao(
                        query_db,
                        RedemptionRecord(
                            position_id=position.position_id,
                            user_id=user_id,
                            fund_code=position.fund_code,
                            shares=record['shares'],
                            nav_price=record['unit_price'],
                            redemption_date=tx_date,
                            # 确认金额 = **实际到账**(已扣赎回费),与买入侧同一写法;此前这里漏传,
                            # 353 条赎回只有 2 条有值(2026-09-22 修):份额×净值是未扣费毛额,
                            # 拿它当赎回收款会把赎回费算成收入
                            amount=record.get('amount') or None,
                            remark=remark,
                        ),
                    )
                    imported_redemptions += 1
                    await query_db.flush()
                    if await cls._get_remaining_shares(query_db, position.position_id) <= (
                        IMPORTED_FULL_REDEMPTION_TOLERANCE
                    ):
                        position.status = POSITION_STATUS_FULLY_REDEEMED
                        position.del_flag = '2'
            except Exception as exc:
                # 带上异常类型:只写 str(exc) 时 KeyError 会显示成一个裸词(如 'origin'),无法定位
                errors.append({'fund_code': record.get('fund_code', ''), 'error': f'{type(exc).__name__}: {exc}'})
                continue

        return positions_created, errors, imported_purchases, imported_redemptions, skipped

    @staticmethod
    def _history_row(row, *, direction: str, record_id: int, origin: str) -> dict:
        """把库里已有的买卖记录(手输 / 上次导入)拼成重建队列的一项:只重挂,不重新落库。

        字段名与本次新增记录一致,判重函数才能两侧可比(见 `statement_import_merge`)。
        """
        return {
            'fund_code': row.fund_code,
            'fund_name': row.fund_name,
            'date': row.tx_date.isoformat() if row.tx_date else None,
            'type': '买入' if direction == DIRECTION_PURCHASE else '赎回',
            'shares': float(row.shares) if row.shares else 0,
            'unit_price': float(row.unit_price) if row.unit_price else 0,
            'amount': float(row.amount) if row.amount else 0,
            'origin': origin,
            'record_id': record_id,
        }

    @classmethod
    async def _imported_rows(cls, query_db: AsyncSession, position_ids: list[int], remark_prefix: str) -> list[dict]:
        """库里已有的导入记录(按 remark 前缀圈范围):前缀给到平台则只取本平台,只给「导入:」则取全部平台。"""
        purchases = await PurchaseRecordDao.get_imported_purchase_records(query_db, position_ids, remark_prefix)
        redemptions = await RedemptionRecordDao.get_imported_redemption_records(query_db, position_ids, remark_prefix)
        rows = [
            cls._history_row(row, direction=DIRECTION_PURCHASE, record_id=row.purchase_id, origin=ORIGIN_EXISTING)
            for row in purchases
        ]
        rows += [
            cls._history_row(row, direction=DIRECTION_REDEMPTION, record_id=row.redemption_id, origin=ORIGIN_EXISTING)
            for row in redemptions
        ]
        return rows

    @classmethod
    async def _hand_rows(cls, query_db: AsyncSession, position_ids: list[int]) -> list[dict]:
        """手工录入的记录(remark 不带导入前缀):始终保留,重挂回重建后的持仓。"""
        purchases = await PurchaseRecordDao.get_original_purchase_records(query_db, position_ids, IMPORT_REMARK_PREFIX)
        redemptions = await RedemptionRecordDao.get_original_redemption_records(
            query_db, position_ids, IMPORT_REMARK_PREFIX
        )
        rows = [
            cls._history_row(row, direction=DIRECTION_PURCHASE, record_id=row.purchase_id, origin=ORIGIN_HAND)
            for row in purchases
        ]
        rows += [
            cls._history_row(row, direction=DIRECTION_REDEMPTION, record_id=row.redemption_id, origin=ORIGIN_HAND)
            for row in redemptions
        ]
        return rows

    @classmethod
    async def _relink_record(cls, query_db: AsyncSession, record: dict, position: UserFundPosition) -> None:
        """把已有记录(手输 / 上次导入)重挂到重建后的持仓上:金额与份额一个字节都不改。

        赎回重挂后要复判「是否已全额赎回」——持仓头表是整表重建的,不在这里标回已清仓,下次读
        就会被当成「在用」;阈值按来源分(手输 0.01、导入 0.5),因为导入份额经文件换算有精度差。
        """
        if direction_of(record['type']) == DIRECTION_PURCHASE:
            await PurchaseRecordDao.update_purchase_position_dao(query_db, record['record_id'], position.position_id)
            return
        await RedemptionRecordDao.update_redemption_position_dao(query_db, record['record_id'], position.position_id)
        await query_db.flush()
        tolerance = (
            ORIGINAL_FULL_REDEMPTION_TOLERANCE
            if record['origin'] == ORIGIN_HAND
            else IMPORTED_FULL_REDEMPTION_TOLERANCE
        )
        if await cls._get_remaining_shares(query_db, position.position_id) <= tolerance:
            position.status = POSITION_STATUS_FULLY_REDEEMED
            position.del_flag = '2'

    @staticmethod
    def _replay_order(record: dict) -> tuple:
        """重建重放顺序:日期升序;同日买入先于赎回(赎回建立在其买入之上);记录 id 兜底稳定。

        顺序错了会连锁坏事:同日赎回先于买入重放会触发全额赎回软删,
        随后的买入另建新持仓行,一笔持仓被拆成两代。
        """
        return (record['date'] or '', 0 if record['type'] == '买入' else 1, record['record_id'])

    @classmethod
    async def rebuild_positions_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int
    ) -> dict:
        """「重建持仓」:头表全删,按日期升序重放全部流水并重挂 position_id。

        与导入确认共用同一套重放机制(_history_row/_relink_record),但取数按 user_id
        直取流水表而非按持仓圈范围——专为「二级清空后流水悬空」的修复场景:
        流水自带 user_id+fund_code,不依赖旧 position_id,悬空记录也能归组重建。
        单事务提交;成功后补快照全量重建(失败不回滚,可手动重建收敛)。
        """
        purchases = await PurchaseRecordDao.get_all_records_for_user(query_db, user_id)
        redemptions = await RedemptionRecordDao.get_all_records_for_user(query_db, user_id)
        if not purchases and not redemptions:
            raise ServiceWarning(message='没有可用的交易记录，无法重建持仓')

        def origin_of(remark: str | None) -> str:
            return ORIGIN_EXISTING if (remark or '').startswith(IMPORT_REMARK_PREFIX) else ORIGIN_HAND

        queue = [
            cls._history_row(row, direction=DIRECTION_PURCHASE, record_id=row.purchase_id, origin=origin_of(row.remark))
            for row in purchases
        ] + [
            cls._history_row(row, direction=DIRECTION_REDEMPTION, record_id=row.redemption_id, origin=origin_of(row.remark))
            for row in redemptions
        ]
        queue.sort(key=cls._replay_order)

        created = 0
        errors: list[dict] = []
        try:
            await PositionDao.delete_all_positions_for_user(query_db, user_id)
            await query_db.flush()
            for record in queue:
                fund = await FundDao.get_fund_by_code(query_db, record['fund_code'])
                if not fund:
                    errors.append({'fund_code': record['fund_code'], 'error': f"基金 {record['fund_code']} 不存在，跳过"})
                    continue
                position = await PositionDao.get_active_position_by_fund(query_db, user_id, record['fund_code'])
                if not position:
                    position = await PositionDao.add_position_dao(
                        query_db,
                        UserFundPosition(user_id=user_id, fund_code=record['fund_code'], status=POSITION_STATUS_NORMAL),
                    )
                    created += 1
                await cls._relink_record(query_db, record, position)
            await query_db.commit()
            logger.info(
                f'[持仓] 从交易记录重建持仓 user_id={user_id} 记录={len(queue)} '
                f'建仓={created} 跳过={len(errors)}'
            )
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[持仓] 从交易记录重建持仓失败回滚 user_id={user_id} | {e}')
            raise e

        snapshot_ok, snapshot_message = await cls._rebuild_snapshots(query_db, redis, user_id)
        return {
            'positionsCreated': created,
            'recordsRelinked': len(queue),
            'snapshotRebuilt': snapshot_ok,
            'snapshotMessage': snapshot_message,
            'errors': errors,
        }

    @classmethod
    async def _rebuild_snapshots(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int
    ) -> tuple[bool, str]:
        """交易落库后补一次快照全量重建;返回 (是否重建成功, 给使用者看的说明)。

        只对「重建被占用」这一类失败重试(上一次重建仍在跑 / 冷却窗口未过):重建实测 4~100 秒,
        占锁者通常正是上一次导入触发的重建;其它异常立即判失败,**不重试**——否则会把真错掩盖成
        "稍后重试就好"。

        每次重试前先 rollback 再等待:绝不在持有事务/连接锁的状态下休眠,否则会把无关的锁一起拖住。
        失败不再"只写日志":状态随 `snapshotRebuilt / snapshotRebuildMessage` 回到界面
        (2026-09-20 实测导入 25 行成功、快照却停在旧份额,界面上完全看不出来)。
        """
        for attempt in range(1, REBUILD_RETRY_ATTEMPTS + 1):
            try:
                result = await SnapshotService.rebuild_from_transactions_services(
                    query_db, redis, user_id
                )
                logger.info(
                    f'[导入] 快照重建完成 user_id={user_id} 快照={result["rebuilt"]["snapshotsCreated"]} '
                    f'现金流={result["rebuilt"]["cashFlowsCreated"]} 第={attempt} 次尝试'
                )
                return True, ''
            except ServiceWarning as exc:
                await query_db.rollback()
                if REBUILD_BUSY_MARKER not in str(exc):
                    logger.warning(f'[导入] 快照重建失败 user_id={user_id} | {exc}')
                    return False, REBUILD_NOT_DONE_MESSAGE
                if attempt < REBUILD_RETRY_ATTEMPTS:
                    logger.info(
                        f'[导入] 快照重建被占用,{REBUILD_RETRY_DELAY_SECONDS}s 后重试 '
                        f'user_id={user_id} 第 {attempt} 次 | {exc}'
                    )
                    await asyncio.sleep(REBUILD_RETRY_DELAY_SECONDS)
                    continue
                logger.warning(
                    f'[导入] 快照重建被占用,重试 {REBUILD_RETRY_ATTEMPTS} 次仍失败 '
                    f'user_id={user_id} | {exc}'
                )
                return False, REBUILD_NOT_DONE_MESSAGE
            except Exception as exc:
                await query_db.rollback()
                logger.warning(f'[导入] 快照重建失败(不影响导入结果) user_id={user_id} | {exc}')
                return False, REBUILD_NOT_DONE_MESSAGE

    @staticmethod
    def order_confirm_date(order_date: str, order_minutes: int) -> str:
        """下单日 + 下单时刻 → 确认日;实现见 `position_calc_util.order_confirm_date`。"""
        return shared_order_confirm_date(order_date, order_minutes)

    @classmethod
    def _apply_order_cutoff(cls, records: list[dict]) -> list[Issue]:
        """列表式截图的确认日切分:15:00 后下单顺延到下一交易日。

        只对**识别到时刻**的记录改日期;识别不到的保持原值并产出告警——静默按当日处理会把
        15:00 后的单子整整算早一天(份额、成本、现金流时点全偏),必须让用户看得见。
        """
        warnings: list[Issue] = []
        for record in records:
            minutes = record.get('_order_minutes')
            if minutes is None:
                warnings.append(
                    Issue(
                        level='warning',
                        field='date',
                        message=ORDER_TIME_UNKNOWN_MESSAGE,
                        row=int(record.get('row') or 0),
                        page=int(record.get('page') or 0),
                    )
                )
                continue
            if minutes > ORDER_CUTOFF_MINUTES and record.get('date'):
                record['date'] = cls.order_confirm_date(record['date'], minutes)
                record['_confirm_shifted'] = True
        return warnings

    @classmethod
    async def _apply_nav_shares(cls, query_db: AsyncSession, redis: aioredis.Redis, records: list[dict]) -> None:
        """列表式截图没有份额:按「该交易日净值」换算,净值未发布则标记待确认(落库 status=0 只记金额)。"""
        for record in records:
            # 分红行按定义「份额与金额不同步」,不能拿金额去换份额:
            # 现金分红是 0 份额 + 负金额,换算出来会是负份额(红利再投资则份额已由文件给出)
            if record.get('dividend') or record.get('shares') or not record.get('fund_code') or not record.get('date'):
                continue
            resolved = await AkshareService.resolve_target_nav(
                query_db, redis, record['fund_code'], date.fromisoformat(record['date'])
            )
            record['nav_pending'] = resolved is None
            if resolved is not None and record.get('amount'):
                record['unit_price'] = resolved[1]
                record['shares'] = round(record['amount'] / resolved[1], 4)

    @staticmethod
    def _purchase_shares(record: dict) -> tuple[float, float, bool]:
        """买入的份额与成本价:文件给了份额就按文件;只有金额(列表式截图/份额列为空)则
        返回待确认 —— 金额照记、份额与净值留 0,与手工录入「净值未发布」时的口径一致。

        不在这里补查净值:预览阶段已经算过一次(见 _apply_nav_shares),confirm 再查会让
        预览与实际落库不一致,还多一次外部调用。
        """
        shares = float(record.get('shares') or 0)
        if shares > 0:
            return shares, float(record.get('unit_price') or 0), False
        pending = bool(record.get('nav_pending')) or float(record.get('amount') or 0) > 0
        return 0.0, 0.0, pending

    @classmethod
    async def _get_remaining_shares(cls, query_db: AsyncSession, position_id: int) -> float:
        """计算持仓剩余份额(买入 - 未删赎回)。"""
        purchases = await PurchaseRecordDao.get_purchase_records(query_db, position_id)
        redemptions = await RedemptionRecordDao.get_redemption_records(query_db, position_id)
        return remaining_shares(purchases, redemptions)

    # ==================== 内部:组装 ====================

    @staticmethod
    def _import_remark(record: dict, platform: str) -> str:
        """导入记录的备注:「导入:<平台>: 基金名」+ 用户补的备注。

        前缀带平台是判重作用域的锚:下次导入同一平台时用 `导入:<平台>:%` 圈出「已有」一侧;
        手输记录不含这个前缀,两者天然分开(见 statement_import_merge)。

        分红行额外带上「| 红利再投资 / | 现金分红」:账本没有独立的分红表(分红就落在买入/赎回表里),
        备注是**持久化的唯一区分依据**——交易记录页的备注列靠它认出这是分红,而不是普通的买卖。
        """
        base = f'{IMPORT_REMARK_PREFIX}{platform}: {record.get("fund_name") or ""}'.strip()
        dividend = (record.get('dividend') or '').strip()
        if dividend:
            base = f'{base} | {dividend}'
        extra = (record.get('remark') or '').strip()
        return f'{base} | {extra}' if extra else base

    @staticmethod
    def _to_preview_row(record: dict) -> dict:
        return {
            'row': record.get('row'),
            'type': '买入' if direction_of(record['type']) == DIRECTION_PURCHASE else '赎回',
            # 分红行(红利再投资/现金分红)才非空:预览页的「类型」列据此显示对应徽标,而不是笼统的「买入」
            'dividend': record.get('dividend', ''),
            'fundCode': record.get('fund_code', ''),
            'fundName': record.get('fund_name', ''),
            'date': record.get('date'),
            'amount': record.get('amount', 0),
            'shares': record.get('shares', 0),
            'unitPrice': record.get('unit_price', 0),
            'fee': record.get('fee', 0),
            'orderNo': record.get('order_no'),
            'status': 'pending',
            # 列表式截图:份额按交易日净值换算,净值未发布则待确认(落库 status=0 只记金额)
            'navPending': bool(record.get('nav_pending')),
            'resolveNote': record.get('resolve_note', ''),
            # 新增字段:来源可追溯(文件类型 / 页码或行号 / 解析层 / 置信度)
            'page': record.get('page'),
            'layer': record.get('layer'),
            'confidence': record.get('confidence'),
            'adapter': record.get('adapter'),
        }

    @staticmethod
    def _to_issue_row(issue: Issue) -> dict:
        row = {'error': issue.message, 'row': issue.row, 'field': issue.field, 'page': issue.page}
        if issue.level == 'warning':
            row['warning'] = issue.message
        return row
