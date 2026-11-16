"""持仓模块 DAO(数据访问层):赎回记录。"""

from datetime import date

from sqlalchemy import Select, delete, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_fund.entity.do.fund_do import Fund
from module_portfolio.entity.do.position_do import UserFundPosition
from module_portfolio.entity.do.redemption_record_do import RedemptionRecord


class RedemptionRecordDao:
    """赎回记录数据库操作层。"""

    # ==================== 读 ====================

    @classmethod
    async def get_redemption_records(
        cls, db: AsyncSession, position_id: int, include_deleted: bool = False
    ) -> list[RedemptionRecord]:
        """获取持仓的全部赎回记录(按日期升序)。

        历史快照/现金流场景需含已删记录(全额赎回软删后交易仍要参与计算)。
        """
        conditions = [RedemptionRecord.position_id == position_id]
        if not include_deleted:
            conditions.append(RedemptionRecord.del_flag == '0')
        result = await db.execute(
            select(RedemptionRecord)
            .where(*conditions)
            .order_by(RedemptionRecord.redemption_date)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_redemption_records_by_fund(
        cls, db: AsyncSession, user_id: int, fund_code: str
    ) -> list[RedemptionRecord]:
        """获取「我」在该基金的全部赎回记录(按日期升序,含已删——历史全量,跨持仓不断档)。

        必须带 user_id:理由同买入侧(两个账号买同一只基金时不能互相串)。
        """
        result = await db.execute(
            select(RedemptionRecord)
            .where(
                RedemptionRecord.user_id == user_id,
                RedemptionRecord.fund_code == fund_code,
            )
            .order_by(RedemptionRecord.redemption_date)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_original_redemption_records(
        cls, db: AsyncSession, position_ids: list[int], remark_prefix: str
    ) -> list:
        """查原始(手输)赎回记录——remark 不以导入前缀开头即原始数据,交易导入合并时保留并重挂持仓。

        不能再用「remark 为空」判定:手输赎回允许填备注(见 position_vo),
        那种记录会被「非空即导入」误判成导入数据,下次导入时被物理删掉。
        返回 Row(fund_code/fund_name/redemption_id/tx_date/shares/unit_price/amount)。
        """
        if not position_ids:
            return []
        result = await db.execute(
            select(
                Fund.code.label('fund_code'),
                Fund.name.label('fund_name'),
                RedemptionRecord.redemption_id,
                RedemptionRecord.redemption_date.label('tx_date'),
                RedemptionRecord.shares,
                RedemptionRecord.nav_price.label('unit_price'),
                (RedemptionRecord.shares * RedemptionRecord.nav_price).label('amount'),
            )
            .join(UserFundPosition, UserFundPosition.position_id == RedemptionRecord.position_id)
            .join(Fund, Fund.code == UserFundPosition.fund_code)
            .where(
                RedemptionRecord.position_id.in_(position_ids),
                func.trim(func.coalesce(RedemptionRecord.remark, '')).not_like(f'{remark_prefix}%'),
            )
        )
        return list(result.all())

    @classmethod
    async def get_shares_by_date_and_fund(
        cls, db: AsyncSession, position_ids: list[int], start_date: date, end_date: date
    ) -> dict[tuple[date, str], float]:
        """按「日期 + 基金」聚合赎回份额({(日期, 基金代码): 份额})。

        供收益率口径判定「记录不完整」:某天某只基金的赎回份额超过当天快照持有份额时,回款会大于
        组合实际被移走的市值,那部分差额不是收益(2026-09-20 实测 9 天假涨)。含已删记录,口径与
        `get_totals_by_date` 一致。
        """
        if not position_ids:
            return {}
        result = await db.execute(
            select(
                RedemptionRecord.redemption_date,
                RedemptionRecord.fund_code,
                func.sum(RedemptionRecord.shares),
            )
            .where(
                RedemptionRecord.position_id.in_(position_ids),
                RedemptionRecord.redemption_date >= start_date,
                RedemptionRecord.redemption_date <= end_date,
                RedemptionRecord.status == '1',
            )
            .group_by(RedemptionRecord.redemption_date, RedemptionRecord.fund_code)
        )
        return {
            (row[0], str(row[1])): float(row[2] or 0) for row in result.all()
        }

    @classmethod
    async def get_totals_by_date(
        cls, db: AsyncSession, position_ids: list[int], start_date: date, end_date: date
    ) -> dict[date, float]:
        """按日期聚合已确认赎回到账金额({日期: 当日赎回总额}),供收益率口径的现金流剥离。

        用「总额」而不是现金流表的当日净额(同日买入会抵消掉赎回,见买入侧同名方法);
        含已删记录:全额赎回会软删持仓与记录,历史资金流出不能因此断档。
        待确认记录(status='0')到账金额尚未确定,不计入。
        """
        if not position_ids:
            return {}
        result = await db.execute(
            select(
                RedemptionRecord.redemption_date,
                func.sum(RedemptionRecord.shares * RedemptionRecord.nav_price),
            )
            .where(
                RedemptionRecord.position_id.in_(position_ids),
                RedemptionRecord.redemption_date >= start_date,
                RedemptionRecord.redemption_date <= end_date,
                RedemptionRecord.status == '1',
            )
            .group_by(RedemptionRecord.redemption_date)
        )
        return {row[0]: float(row[1] or 0) for row in result.all()}

    @classmethod
    def build_transactions_select(cls, user_id: int) -> Select:
        """交易明细的「赎回」一侧:统一列形(与买入侧逐列同构),供 Service 做 union_all。

        不过滤 del_flag:全额赎回软删的记录同样是历史交易,交易页历来要显示(旧实现传
        include_deleted=True)。
        """
        return (
            select(
                literal('赎回').label('type'),
                literal('redemption').label('source'),
                RedemptionRecord.redemption_id.label('record_id'),
                RedemptionRecord.fund_code.label('fund_code'),
                func.coalesce(Fund.name, '').label('fund_name'),
                RedemptionRecord.redemption_date.label('tx_date'),
                RedemptionRecord.shares.label('shares'),
                RedemptionRecord.nav_price.label('price'),
                RedemptionRecord.amount.label('amount'),
                RedemptionRecord.status.label('status'),
                RedemptionRecord.remark.label('remark'),
            )
            .select_from(RedemptionRecord)
            .join(Fund, Fund.code == RedemptionRecord.fund_code, isouter=True)
            .where(RedemptionRecord.user_id == user_id)
        )

    # ==================== 写(只 flush,事务由 Service 控制) ====================

    @classmethod
    async def add_redemption_record_dao(cls, db: AsyncSession, record: RedemptionRecord) -> RedemptionRecord:
        """新增赎回记录(flush 回填自增主键)。"""
        db.add(record)
        await db.flush()
        return record

    @classmethod
    async def update_redemption_position_dao(
        cls, db: AsyncSession, redemption_id: int, position_id: int
    ) -> None:
        """更新赎回记录所属持仓(导入合并时重挂)。"""
        await db.execute(
            update(RedemptionRecord)
            .where(RedemptionRecord.redemption_id == redemption_id)
            .values(position_id=position_id)
        )

    @classmethod
    async def get_imported_redemption_records(
        cls, db: AsyncSession, position_ids: list[int], remark_prefix: str
    ) -> list:
        """查库里已有的导入赎回记录(按 remark 前缀圈范围),用于判重与重挂。

        与 `get_original_redemption_records` 同形,**不过滤 `del_flag`**:软删(全额赎回后清掉)的
        记录同样是「已经导过这一笔」的证据,过滤掉会让同一笔再插一遍;而且它们也要重挂 position_id。
        """
        if not position_ids:
            return []
        result = await db.execute(
            select(
                Fund.code.label('fund_code'),
                Fund.name.label('fund_name'),
                RedemptionRecord.redemption_id,
                RedemptionRecord.redemption_date.label('tx_date'),
                RedemptionRecord.shares,
                RedemptionRecord.nav_price.label('unit_price'),
                RedemptionRecord.amount,
            )
            .join(UserFundPosition, UserFundPosition.position_id == RedemptionRecord.position_id)
            .join(Fund, Fund.code == UserFundPosition.fund_code)
            .where(
                RedemptionRecord.position_id.in_(position_ids),
                func.trim(func.coalesce(RedemptionRecord.remark, '')).like(f'{remark_prefix}%'),
            )
        )
        return list(result.all())

    @classmethod
    async def get_all_records_for_user(cls, db: AsyncSession, user_id: int) -> list:
        """全量赎回记录(按 user_id,不依赖 position_id 存活):「重建持仓」的取数入口。

        列形对齐 get_imported_redemption_records 并多带 remark;Fund 按记录自身的
        fund_code 直连,二级清空后悬空的记录也能取到(理由同买入侧)。
        """
        result = await db.execute(
            select(
                RedemptionRecord.redemption_id,
                RedemptionRecord.fund_code,
                func.coalesce(Fund.name, '').label('fund_name'),
                RedemptionRecord.redemption_date.label('tx_date'),
                RedemptionRecord.shares,
                RedemptionRecord.nav_price.label('unit_price'),
                RedemptionRecord.amount,
                RedemptionRecord.remark,
            )
            .outerjoin(Fund, Fund.code == RedemptionRecord.fund_code)
            .where(RedemptionRecord.user_id == user_id)
            .order_by(RedemptionRecord.redemption_date, RedemptionRecord.redemption_id)
        )
        return list(result.all())

    @classmethod
    async def get_record_by_id_for_user(
        cls, db: AsyncSession, record_id: int, user_id: int
    ) -> RedemptionRecord | None:
        """按主键取单条赎回记录(含行级归属校验,软删持仓的记录也可见)。"""
        result = await db.execute(
            select(RedemptionRecord).where(
                RedemptionRecord.redemption_id == record_id,
                RedemptionRecord.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @classmethod
    async def delete_record_dao(cls, db: AsyncSession, record: RedemptionRecord) -> None:
        """物理删除单条赎回记录(删除交易场景,不经 del_flag)。"""
        await db.delete(record)

    @classmethod
    async def delete_all_for_user(cls, db: AsyncSession, user_id: int) -> int:
        """物理删除该用户的全部赎回记录(含已软删的,历史流水不留残余)。

        按 user_id 而不是按持仓 ID:理由同买入侧(清空持仓后那批流水也要删得掉)。
        """
        result = await db.execute(delete(RedemptionRecord).where(RedemptionRecord.user_id == user_id))
        return result.rowcount or 0

    @classmethod
    async def get_pending_records(cls, db: AsyncSession, position_ids: list[int]) -> list[RedemptionRecord]:
        """获取待确认的赎回记录(status='0',所选日期净值发布前录入)。"""
        if not position_ids:
            return []
        result = await db.execute(
            select(RedemptionRecord).where(
                RedemptionRecord.position_id.in_(position_ids),
                RedemptionRecord.status == '0',
            )
        )
        return list(result.scalars().all())
