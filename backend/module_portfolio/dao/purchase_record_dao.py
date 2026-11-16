"""持仓模块 DAO(数据访问层):买入记录。"""

from datetime import date

from sqlalchemy import Select, delete, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_fund.entity.do.fund_do import Fund
from module_portfolio.entity.do.position_do import UserFundPosition
from module_portfolio.entity.do.purchase_record_do import PurchaseRecord


class PurchaseRecordDao:
    """买入记录数据库操作层。"""

    # ==================== 读 ====================

    @classmethod
    async def get_purchase_records(cls, db: AsyncSession, position_id: int) -> list[PurchaseRecord]:
        """获取持仓的全部买入记录(按日期升序)。"""
        result = await db.execute(
            select(PurchaseRecord)
            .where(PurchaseRecord.position_id == position_id)
            .order_by(PurchaseRecord.purchase_date)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_purchase_records_by_fund(
        cls, db: AsyncSession, user_id: int, fund_code: str
    ) -> list[PurchaseRecord]:
        """获取「我」在该基金的全部买入记录(按日期升序,跨持仓——同基金清仓再买后历史不断档)。

        必须带 user_id:流水原先只能按 fund_code 查,两个账号买同一只基金时会把两边的记录
        混在一起(2026-09-21 修)。
        """
        result = await db.execute(
            select(PurchaseRecord)
            .where(
                PurchaseRecord.user_id == user_id,
                PurchaseRecord.fund_code == fund_code,
            )
            .order_by(PurchaseRecord.purchase_date)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_original_purchase_records(cls, db: AsyncSession, position_ids: list[int], remark_prefix: str) -> list:
        """查原始(手输)买入记录——remark 不以导入前缀开头即原始数据,交易导入合并时保留并重挂持仓。

        不能再用「remark 为空」判定:手输买入允许填备注(见 position_vo),
        那种记录会被「非空即导入」误判成导入数据,下次导入时被物理删掉。
        返回 Row(fund_code/fund_name/purchase_id/tx_date/shares/unit_price/amount)。
        """
        if not position_ids:
            return []
        result = await db.execute(
            select(
                Fund.code.label('fund_code'),
                Fund.name.label('fund_name'),
                PurchaseRecord.purchase_id,
                PurchaseRecord.purchase_date.label('tx_date'),
                PurchaseRecord.shares,
                PurchaseRecord.cost_price.label('unit_price'),
                (PurchaseRecord.shares * PurchaseRecord.cost_price).label('amount'),
            )
            .join(UserFundPosition, UserFundPosition.position_id == PurchaseRecord.position_id)
            .join(Fund, Fund.code == UserFundPosition.fund_code)
            .where(
                PurchaseRecord.position_id.in_(position_ids),
                func.trim(func.coalesce(PurchaseRecord.remark, '')).not_like(f'{remark_prefix}%'),
            )
        )
        return list(result.all())

    @classmethod
    async def get_totals_by_date(
        cls, db: AsyncSession, position_ids: list[int], start_date: date, end_date: date
    ) -> dict[date, float]:
        """按日期聚合已确认买入金额({日期: 当日资金进出,申购为正、现金分红为负}),供收益率口径的现金流剥离。

        用「总额」而不是现金流表的当日净额:同一天既有买入又有赎回时净额会被抵消,
        按「净额为正才算赎回」的剥离逻辑就取不到赎回,该笔赎回会变成凭空亏损。
        待确认记录(status='0')份额尚未确定,不计入。

        取 `amount` 优先、缺失才回退「份额 × 成本价」:现金分红落成「`shares=0` + `amount` 负额」的行,
        按份额算恒为 0 → 分红额进不了剥离 → 除息日(净值已扣分红)会被整段算成**假亏损**。
        红利再投资是「`amount` 为空 + 成本价 0」,回退后仍是 0(份额白涨、无现金进出),符合预期。
        """
        if not position_ids:
            return {}
        result = await db.execute(
            select(
                PurchaseRecord.purchase_date,
                func.sum(
                    func.coalesce(
                        PurchaseRecord.amount,
                        PurchaseRecord.shares * PurchaseRecord.cost_price,
                    )
                ),
            )
            .where(
                PurchaseRecord.position_id.in_(position_ids),
                PurchaseRecord.purchase_date >= start_date,
                PurchaseRecord.purchase_date <= end_date,
                PurchaseRecord.status == '1',
            )
            .group_by(PurchaseRecord.purchase_date)
        )
        return {row[0]: float(row[1] or 0) for row in result.all()}

    @classmethod
    def build_transactions_select(cls, user_id: int) -> Select:
        """交易明细的「买入」一侧:统一列形(与赎回侧逐列同构),供 Service 做 union_all。

        纯语句构造、不碰 DB:便于单测直接编译断言过滤条件。
        列形(两侧必须一致):type / source / record_id / fund_code / fund_name
                            / tx_date / shares / price / amount / status / remark
        fund_name 左连 fund(元数据缺失给空串);fund_code 取记录自身。
        """
        return (
            select(
                literal('买入').label('type'),
                literal('purchase').label('source'),
                PurchaseRecord.purchase_id.label('record_id'),
                PurchaseRecord.fund_code.label('fund_code'),
                func.coalesce(Fund.name, '').label('fund_name'),
                PurchaseRecord.purchase_date.label('tx_date'),
                PurchaseRecord.shares.label('shares'),
                PurchaseRecord.cost_price.label('price'),
                PurchaseRecord.amount.label('amount'),
                PurchaseRecord.status.label('status'),
                PurchaseRecord.remark.label('remark'),
            )
            .select_from(PurchaseRecord)
            .join(Fund, Fund.code == PurchaseRecord.fund_code, isouter=True)
            .where(PurchaseRecord.user_id == user_id)
        )

    # ==================== 写(只 flush,事务由 Service 控制) ====================

    @classmethod
    async def add_purchase_record_dao(cls, db: AsyncSession, record: PurchaseRecord) -> PurchaseRecord:
        """新增买入记录(flush 回填自增主键)。"""
        db.add(record)
        await db.flush()
        return record

    @classmethod
    async def update_purchase_position_dao(cls, db: AsyncSession, purchase_id: int, position_id: int) -> None:
        """更新买入记录所属持仓(导入合并时重挂)。"""
        await db.execute(
            update(PurchaseRecord)
            .where(PurchaseRecord.purchase_id == purchase_id)
            .values(position_id=position_id)
        )

    @classmethod
    async def get_imported_purchase_records(cls, db: AsyncSession, position_ids: list[int], remark_prefix: str) -> list:
        """查该平台已导入的买入记录(remark 以「导入:<平台>:」开头),作为判重的「已有」一侧。

        返回 Row(fund_code/fund_name/purchase_id/tx_date/shares/unit_price/amount),与
        `get_original_purchase_records` 同形——两类记录在重建队列里走同一条「重挂 position_id」分支。
        """
        if not position_ids:
            return []
        result = await db.execute(
            select(
                Fund.code.label('fund_code'),
                Fund.name.label('fund_name'),
                PurchaseRecord.purchase_id,
                PurchaseRecord.purchase_date.label('tx_date'),
                PurchaseRecord.shares,
                PurchaseRecord.cost_price.label('unit_price'),
                PurchaseRecord.amount,
            )
            .join(UserFundPosition, UserFundPosition.position_id == PurchaseRecord.position_id)
            .join(Fund, Fund.code == UserFundPosition.fund_code)
            .where(
                PurchaseRecord.position_id.in_(position_ids),
                func.trim(func.coalesce(PurchaseRecord.remark, '')).like(f'{remark_prefix}%'),
            )
        )
        return list(result.all())

    @classmethod
    async def get_all_records_for_user(cls, db: AsyncSession, user_id: int) -> list:
        """全量买入记录(按 user_id,不依赖 position_id 存活):「重建持仓」的取数入口。

        列形与 get_imported_purchase_records 一致并多带 remark 供来源判定;
        二级清空后 position_id 悬空的记录也能取到——Fund 按记录自身的 fund_code 直连,
        不经持仓表(持仓行已物理删除,经它关联会整批漏掉)。
        """
        result = await db.execute(
            select(
                PurchaseRecord.purchase_id,
                PurchaseRecord.fund_code,
                func.coalesce(Fund.name, '').label('fund_name'),
                PurchaseRecord.purchase_date.label('tx_date'),
                PurchaseRecord.shares,
                PurchaseRecord.cost_price.label('unit_price'),
                PurchaseRecord.amount,
                PurchaseRecord.remark,
            )
            .outerjoin(Fund, Fund.code == PurchaseRecord.fund_code)
            .where(PurchaseRecord.user_id == user_id)
            .order_by(PurchaseRecord.purchase_date, PurchaseRecord.purchase_id)
        )
        return list(result.all())

    @classmethod
    async def get_record_by_id_for_user(
        cls, db: AsyncSession, record_id: int, user_id: int
    ) -> PurchaseRecord | None:
        """按主键取单条买入记录(含行级归属校验,软删持仓的记录也可见)。"""
        result = await db.execute(
            select(PurchaseRecord).where(
                PurchaseRecord.purchase_id == record_id,
                PurchaseRecord.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @classmethod
    async def delete_record_dao(cls, db: AsyncSession, record: PurchaseRecord) -> None:
        """物理删除单条买入记录(删除交易场景,不经 del_flag)。"""
        await db.delete(record)

    @classmethod
    async def delete_all_for_user(cls, db: AsyncSession, user_id: int) -> int:
        """物理删除该用户的全部买入记录(含手工录入的,不区分来源)。

        按 user_id 而不是按持仓 ID:清空持仓后流水仍带账号归属,照样能删干净
        (2026-09-21 改;原先按 position_id 圈范围,清空持仓后那批流水谁都删不到)。
        """
        result = await db.execute(delete(PurchaseRecord).where(PurchaseRecord.user_id == user_id))
        return result.rowcount or 0

    @classmethod
    async def get_pending_records(cls, db: AsyncSession, position_ids: list[int]) -> list[PurchaseRecord]:
        """获取待确认的买入记录(status='0',所选日期净值发布前录入)。"""
        if not position_ids:
            return []
        result = await db.execute(
            select(PurchaseRecord).where(
                PurchaseRecord.position_id.in_(position_ids),
                PurchaseRecord.status == '0',
            )
        )
        return list(result.scalars().all())
