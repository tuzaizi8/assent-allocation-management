"""持仓管理模块 Service(业务逻辑层)。

职责:持仓创建/买入/赎回编排(金额→份额换算、防御性校验、全额赎回软删)
+ 持仓明细聚合 + 交易记录 + 基金可添加性验证 + 事务控制。
"""

from datetime import date, datetime, timedelta

from redis import asyncio as aioredis
from sqlalchemy import func, select, union_all
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from common.enums import RedisInitKeyConfig
from common.response import PageModel
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
from module_portfolio.entity.vo.position_vo import (
    PositionCreateModel,
    PurchaseRecordCreateModel,
    RedemptionRecordCreateModel,
    ValidationResultModel,
)
from module_portfolio.service.position_calc_util import (
    SHARES_ZERO_EPSILON,
    MoneyAccumCurve,
    cost_basis_walk,
    daily_profit,
    fund_realized_profit,
    money_market_value_on,
    nav_at_or_before,
    next_confirm_date,
    purchase_amount,
    remaining_shares,
    shares_held_at_close,
    shares_held_on_pairs,
)
from module_portfolio.service.snapshot_service import SnapshotService
from utils.camel_case_util import CamelCaseUtil
from utils.log import logger

# 全额赎回判断容差(浮点精度:0.00000001 份残留不应阻止软删)
FULL_REDEMPTION_TOLERANCE = 0.0001

# 持仓列表可排序字段(前端排序表头 → 明细字典里的键):只放开三个**派生指标**——
# 它们不是表列,排序得等指标算完(故服务层按需取全量行再排);其余字段不参与排序
POSITION_SORT_KEYS = {
    'current_value': 'currentValue',
    'profit': 'profit',
    'profit_rate': 'profitRate',
}


class PositionService:
    """持仓管理模块服务层。"""

    # ---------- 查询 ----------

    @classmethod
    async def _calculate_position_summary(
        cls, query_db: AsyncSession, redis: aioredis.Redis, position: UserFundPosition
    ) -> dict:
        """计算持仓汇总(剩余份额/持仓成本/市值/持有收益)。

        口径分工(用户决策):汇总只算当前 active 持仓(按 position_id)——清仓后
        再买同基金视为全新基金,不被旧清仓历史拖累;明细展示则按 fund_code 全量
        (见 get_position_detail_services),看历史归明细、算收益归新仓位。

        **成本随赎回结转**(2026-09-22 修):持仓成本 = 剩余份额对应的成本,由
        `cost_basis_walk` 按卖出时的加权平均成本结转得出;此前它等于「全部买入金额」,
        已经卖掉的份额成本仍压在持仓上 → 平均成本与亏损被一起放大。
        """
        purchases = await PurchaseRecordDao.get_purchase_records(query_db, position.position_id)
        redemptions = await RedemptionRecordDao.get_redemption_records(query_db, position.position_id)

        shares_now = remaining_shares(purchases, redemptions)
        _, walked_cost, _ = cost_basis_walk(
            [(p.purchase_date, p.shares, purchase_amount(p)) for p in purchases],
            [(r.redemption_date, r.shares, r.nav_price) for r in redemptions],
        )
        # 已清仓行可能出现负成本(导出件截断导致卖出多于买入):没有剩余份额时按 0 计,
        # 别把负数带进展厅;当前持仓行的份额不会被卖出超过,故不受影响
        total_cost = 0.0 if shares_now <= SHARES_ZERO_EPSILON else max(0.0, walked_cost)
        avg_cost = total_cost / shares_now if shares_now > 0 else 0

        # 会话工厂已设 expire_on_commit=False,净值回源 commit 不会使对象过期;
        # 这里取字符串局部变量是为了让返回 dict 不内嵌 ORM 对象(调用方可能跨事务使用)
        fund = await FundDao.get_fund_by_code(query_db, position.fund_code)
        fund_code = fund.code if fund else position.fund_code
        fund_name = fund.name if fund else ''
        fund_type = fund.fund_type if fund else ''
        current_nav = 0.0
        # 日收益按「上一净值日已持有的份额」算,不能用当前份额:今天买入/加仓的份额昨天并未持有,
        # 用当前份额乘昨日涨跌会把今天的下单算成昨天的收益;净值 T+1 公布,标签固定写「昨日收益」
        prev_nav = 0.0
        prev_nav_date = ''
        # 最新净值日也透出:前端靠它把日收益归到「昨日/今日」档(净值 T+1,更新后自动滚到今日档)
        latest_nav_date = ''
        is_money = bool(fund) and AkshareService.is_money_fund_type(fund_type)
        money_curve = None
        if fund and is_money:
            money_series = await AkshareService.get_money_fund_nav_series(query_db, redis, fund_code)
            if money_series:
                money_curve = MoneyAccumCurve(money_series)
                current_nav = 1.0
                latest_nav_date, prev_nav_date = money_curve.last_two_dates()
        elif fund:
            nav_records = await AkshareService.get_fund_nav(query_db, redis, fund_code)
            if nav_records:
                current_nav = nav_records[-1].get('unit_nav', 0)
                latest_nav_date = nav_records[-1].get('nav_date') or ''
                if len(nav_records) > 1:
                    prev_nav = nav_records[-2].get('unit_nav', current_nav)
                    prev_nav_date = nav_records[-2].get('nav_date') or ''

        # 份额口径走公共工具:日收益族(赎回当日已扣除),与日收益端点和单测锁定的口径一致
        purchase_pairs = [(p.purchase_date, float(p.shares)) for p in purchases]
        redemption_pairs = [(r.redemption_date, float(r.shares)) for r in redemptions]
        if money_curve and latest_nav_date:
            # 货币基金:收益逐日结转进份额,市值按每笔交易从成交日起复利折算
            # (money_market_value_on),持有收益与真实基金 App 逐分一致;
            # 净值恒 1.0,昨日收益 = 最新两根累计收益日的市值差
            #
            # **赎回前移一日**(2026-10-22 修正):money_market_value_on 是市值族口径
            # (传入赎回日 d,内部在 d+1 才扣除)——按赎回当日传入时,当日市值仍按
            # 满份额算,与本函数显示的 remaining_shares(赎回当日已扣的日收益族口径)
            # 相差整个赎回量,profit = 市值 − 成本 凭空多出「假收益」(实证:000198
            # 赎回 300 份当日,市值 1205.89 − 成本 900 = 虚增收益 305.89)。
            # 传入 d−1 让扣除恰好发生在当日,市值与 remaining_shares 同口径。
            redemption_pairs_shifted = [
                (d - timedelta(days=1), s) for d, s in redemption_pairs
            ]
            current_value = money_market_value_on(
                purchase_pairs, redemption_pairs_shifted, money_curve, date.today()
            )
            day_profit = money_market_value_on(
                purchase_pairs, redemption_pairs_shifted, money_curve, date.fromisoformat(latest_nav_date)
            ) - money_market_value_on(
                purchase_pairs, redemption_pairs_shifted, money_curve, date.fromisoformat(prev_nav_date)
            ) if prev_nav_date else 0.0
        else:
            day_profit = (
                daily_profit(
                    shares_held_at_close(purchases, redemptions, prev_nav_date),
                    current_nav,
                    prev_nav,
                )
                if prev_nav_date
                else 0.0
            )
            current_value = shares_now * current_nav
        profit = current_value - total_cost
        profit_rate = (profit / total_cost * 100) if total_cost > 0 else 0

        return {
            'remaining_shares': shares_now,
            'total_cost': total_cost,
            'avg_cost': avg_cost,
            'current_nav': current_nav,
            'daily_profit': day_profit,
            'daily_profit_date': prev_nav_date,
            'latest_nav_date': latest_nav_date,
            'current_value': current_value,
            'profit': profit,
            'profit_rate': profit_rate,
            'fund_code': fund_code,
            'fund_name': fund_name,
            'fund_type': fund_type,
        }

    @classmethod
    async def _confirm_pending_transactions(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int
    ) -> None:
        """懒确认待确认交易:所选日期的净值公布后回填份额/净值并置已确认。

        触发时机=用户访问持仓读取路径(22 点后首次访问即确认,无需定时任务);
        净值仍未发布的记录保持待确认,下次访问再试。确认的 commit 与
        get_fund_nav 回源的 commit 同属"读路径写库"先例。
        """
        # 含已删持仓:待确认赎回可能触发全额赎回软删,软删后记录仍需确认回填
        all_positions = await PositionDao.get_all_positions(query_db, user_id)
        position_ids = [p.position_id for p in all_positions]
        pending_purchases = await PurchaseRecordDao.get_pending_records(query_db, position_ids)
        pending_redemptions = await RedemptionRecordDao.get_pending_records(query_db, position_ids)
        if not pending_purchases and not pending_redemptions:
            return

        confirmed = 0
        for record in pending_purchases:
            resolved = await AkshareService.resolve_target_nav(
                query_db, redis, record.fund_code, record.purchase_date
            )
            if resolved is None:
                continue
            # 只需净值:回填用的日期即记录自身的买入/赎回日,无需目标净值日
            _, nav = resolved
            record.cost_price = nav
            record.shares = float(record.amount or 0) / nav if nav and record.amount else 0.0
            record.status = '1'
            confirmed += 1
        for record in pending_redemptions:
            resolved = await AkshareService.resolve_target_nav(
                query_db, redis, record.fund_code, record.redemption_date
            )
            if resolved is None:
                continue
            # 只需净值:回填用的日期即记录自身的买入/赎回日,无需目标净值日
            _, nav = resolved
            record.nav_price = nav
            record.amount = float(record.shares) * nav
            record.status = '1'
            confirmed += 1

        if confirmed:
            await query_db.commit()
            logger.info(f'[持仓] 待确认交易确认 {confirmed} 笔 user_id={user_id}')
            # 确认改变了份额与成交价,而快照只认已生效交易 → 必须同步重算,否则份额变化要等
            # 下次重建才体现。用全量重建而非按区间补齐:全额赎回会把持仓软删,按 active 持仓
            # 的区间补齐覆盖不到那些历史行(现已是单事务 + 批量写入,毫秒级)。
            try:
                await SnapshotService.rebuild_from_transactions_services(query_db, redis, user_id)
            except Exception as e:
                # 重建失败不能拖垮读路径:交易确认已落库,快照留给下次回填/重建修正
                await query_db.rollback()
                logger.warning(f'[持仓] 待确认确认后重建快照失败 user_id={user_id} | {e}')

    @classmethod
    async def get_position_detail_services(
        cls,
        query_db: AsyncSession,
        redis: aioredis.Redis,
        position_id: int,
        user_id: int,
        *,
        confirm_pending: bool = True,
    ) -> dict | None:
        """获取持仓明细(含买卖历史,驼峰契约)。

        confirm_pending=False 供循环内调用方复用:待确认回填已由入口统一跑过一次,
        逐条再跑会退化成 N+1 次「全量持仓 + 待确认记录」查询。
        """
        if confirm_pending:
            await cls._confirm_pending_transactions(query_db, redis, user_id)
        position = await PositionDao.get_position_by_id(query_db, position_id, user_id)
        if not position:
            return None

        # 会话工厂已设 expire_on_commit=False,净值回源 commit 不再使对象过期;
        # 仍先取局部变量是为了返回 dict 不内嵌 ORM 对象(调用方可能跨事务使用)
        detail_position_id = position.position_id
        fund_code = position.fund_code
        status = position.status
        create_time = position.create_time
        update_time = position.update_time

        summary = await cls._calculate_position_summary(query_db, redis, position)
        # 明细按 fund_code 匹配:同基金清仓后再买换新持仓行,按 code 才能看到全部历史;
        # 同时必须带 user_id——只按 code 会把其它账号同一只基金的流水也捞进来(2026-09-21 修)
        purchases = await PurchaseRecordDao.get_purchase_records_by_fund(query_db, user_id, fund_code)
        redemptions = await RedemptionRecordDao.get_redemption_records_by_fund(query_db, user_id, fund_code)

        # 已实现收益/累计盈亏走**全基金**口径(同一 fund_code 的全部持仓行,含已清仓软删行),
        # 用的就是上面为买卖历史取的两份记录,不额外查询(列表路径同样复用,只是一次内存遍历)
        fund = await FundDao.get_fund_by_code(query_db, fund_code)
        is_money_fund = fund is not None and AkshareService.is_money_fund_type(fund.fund_type)

        def _redeem_price_of(r):
            # 货币基金:赎回单价 = amount/shares(结转后真实到账单价)——nav 恒 1.0 的
            # 名义单价会把每日结转收益全部吞掉,已实现盈亏恒 0(2026-10-08 用户发现)
            if r.shares and getattr(r, 'amount', None) is not None:
                return float(r.amount) / float(r.shares)
            return float(r.nav_price)

        fund_realized = fund_realized_profit(
            purchases,
            redemptions,
            redeem_price_of=_redeem_price_of if is_money_fund else None,
        )

        purchase_records = [
            CamelCaseUtil.transform_result({
                'purchase_id': p.purchase_id,
                'position_id': p.position_id,
                'fund_code': fund_code,
                'shares': float(p.shares),
                'cost_price': float(p.cost_price),
                'purchase_date': p.purchase_date,
                'total_cost': float(p.shares) * float(p.cost_price),
                'status': getattr(p, 'status', '1'),
                'amount': float(p.amount) if p.amount is not None else None,
                'create_time': p.create_time,
                'remark': p.remark,
            })
            for p in purchases
        ]
        redemption_records = [
            CamelCaseUtil.transform_result({
                'redemption_id': r.redemption_id,
                'position_id': r.position_id,
                'fund_code': fund_code,
                'shares': float(r.shares),
                'nav_price': float(r.nav_price),
                'redemption_date': r.redemption_date,
                'total_amount': float(r.shares) * float(r.nav_price),
                'status': getattr(r, 'status', '1'),
                'amount': float(r.amount) if r.amount is not None else None,
                'create_time': r.create_time,
                'remark': r.remark,
            })
            for r in redemptions
        ]

        return CamelCaseUtil.transform_result({
            'position_id': detail_position_id,
            'user_id': user_id,
            'fund_name': summary['fund_name'],
            'fund_code': summary['fund_code'],
            'fund_type': summary['fund_type'],
            'total_shares': summary['remaining_shares'],
            'total_cost': summary['total_cost'],
            'avg_cost_price': summary['avg_cost'],
            'current_value': summary['current_value'],
            'daily_profit': summary['daily_profit'],
            'daily_profit_date': summary['daily_profit_date'],
            'latest_nav_date': summary['latest_nav_date'],
            'profit': summary['profit'],
            'profit_rate': summary['profit_rate'],
            # 已实现收益(该基金历次赎回/清仓结转合计)与累计盈亏 = 持有收益 + 已实现收益
            'realized_profit': fund_realized,
            'total_profit': summary['profit'] + fund_realized,
            'status': status,
            'purchase_records': purchase_records,
            'redemption_records': redemption_records,
            'create_time': create_time,
            'update_time': update_time,
        })

    @classmethod
    async def get_positions_services(
        cls,
        query_db: AsyncSession,
        redis: aioredis.Redis,
        user_id: int,
        page_num: int = 1,
        page_size: int = 10,
        is_page: bool = False,
        status: str | None = None,
        keyword: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> PageModel | list[dict]:
        """获取用户 active 持仓明细(is_page=True 走分页,否则全量;明细逐条组装)。

        sort_by 支持三个**派生指标**(current_value / profit / profit_rate,见 POSITION_SORT_KEYS):
        它们由「份额×净值」与结转成本算出来,SQL 里没有对应列 → 这条路径改为取全量行、算完指标
        在内存里排序、最后自己切片;分页元信息(total/hasNext)与既有契约保持一致。
        缺省与认不出的键都回落「当前市值降序」(列表页的默认视图,持仓量级几十条,全量排序无压力)。
        """
        # 懒确认待确认交易:22 点后净值发布,用户首次访问持仓页即回填份额/净值
        await cls._confirm_pending_transactions(query_db, redis, user_id)
        if not is_page:
            positions = await PositionDao.get_positions(query_db, user_id)
            # 主键在循环前取成局部变量:detail 组装会触发净值回源 commit,
            # 先取主键可让循环体不依赖头部对象(会话已关过期,此处属防御性写法)
            position_ids = [pos.position_id for pos in positions]
            result = []
            for position_id in position_ids:
                detail = await cls.get_position_detail_services(
                    query_db, redis, position_id, user_id, confirm_pending=False
                )
                if detail:
                    result.append(detail)
            return result

        # 分页只作用于头表:明细分页后再逐条组装,避免全量持仓先算一遍汇总(重接口 N+1 的量级收敛)
        sort_key = POSITION_SORT_KEYS.get((sort_by or '').strip().lower(), 'currentValue')
        # 排序键要算完指标才知道,先切页会切出错序 → 取全量头表行,排完再自己切片
        # (PageUtil 在 is_page=False 时直接返回行列表,没有 PageModel 信封)
        head_rows = await PositionDao.get_positions_page(
            query_db, user_id, page_num, page_size, status, keyword, is_page=False
        )
        details = []
        for row in head_rows:
            detail = await cls.get_position_detail_services(
                query_db, redis, int(row['positionId']), user_id, confirm_pending=False
            )
            if detail:
                details.append(detail)
        # list.sort 稳定:同值行保持 DB 的 position_id 序,翻页不会抖动
        details.sort(
            key=lambda detail: detail.get(sort_key) or 0,
            reverse=(sort_order or 'desc').strip().lower() != 'asc',
        )
        # 行数据以明细为准:头表驼峰 dict 只有主键,汇总/买卖历史都在明细里
        total = len(details)
        start = (page_num - 1) * page_size
        return PageModel(
            rows=details[start : start + page_size],
            page_num=page_num,
            page_size=page_size,
            total=total,
            has_next=page_num * page_size < total,
        )

    @classmethod
    async def get_overview_services(cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int) -> dict:
        """获取持仓概览(总市值/总成本/总盈亏 + 明细列表)。"""
        positions = await cls.get_positions_services(query_db, redis, user_id)
        total_value = sum(p['currentValue'] for p in positions)
        total_cost = sum(p['totalCost'] for p in positions)
        total_profit = total_value - total_cost
        profit_rate = (total_profit / total_cost * 100) if total_cost > 0 else 0
        return {
            'totalValue': round(total_value, 2),
            'totalCost': round(total_cost, 2),
            'totalProfit': round(total_profit, 2),
            'profitRate': round(profit_rate, 2),
            'positions': positions,
        }

    @classmethod
    async def get_transactions_services(
        cls,
        query_db: AsyncSession,
        user_id: int,
        page_num: int = 1,
        page_size: int = 10,
        tx_type: str | None = None,
    ) -> PageModel:
        """获取用户交易记录(买入+赎回,按日期倒序分页)。

        取数直接落到两张流水表(user_id 过滤),在 SQL 里 union_all + 排序 + LIMIT/OFFSET:
        查询数固定 2 条(列表 + count),不再随持仓数量增长(旧实现 1+N+2N ≈ 490 次);清空持仓后
        保留下来的历史流水也照常查得到——流水自带账号归属(2026-09-21)。列表与 total 同源于
        一个 union,分页元数据与数据必然一致。
        """
        selectors = []
        if tx_type in (None, '买入'):
            selectors.append(PurchaseRecordDao.build_transactions_select(user_id))
        if tx_type in (None, '赎回'):
            selectors.append(RedemptionRecordDao.build_transactions_select(user_id))
        if not selectors:
            # 未知类型:旧实现是「筛选后为空」,这里保持同一结果,而不是让 union_all 无参报错
            return PageModel(
                rows=[], page_num=page_num, page_size=page_size, total=0, has_next=False
            )
        merged = union_all(*selectors).subquery()

        count_result = await query_db.execute(select(func.count()).select_from(merged))
        total = count_result.scalar() or 0
        offset = (page_num - 1) * page_size
        result = await query_db.execute(
            select(merged)
            # 同一天的多笔必须有确定次序:旧实现靠持仓遍历顺序,配 LIMIT/OFFSET 会漏行/重行
            .order_by(merged.c.tx_date.desc(), merged.c.source.desc(), merged.c.record_id.desc())
            .limit(page_size)
            .offset(offset)
        )
        return PageModel(
            rows=[
                CamelCaseUtil.transform_result(cls._transaction_row(row))
                for row in result.mappings()
            ],
            page_num=page_num,
            page_size=page_size,
            total=total,
            has_next=page_num * page_size < total,
        )

    @classmethod
    async def get_all_transactions_services(cls, query_db: AsyncSession, user_id: int) -> list[dict]:
        """全量交易记录(不分页):交易导出的取数入口,复用流水 union 同一列形。"""
        merged = union_all(
            PurchaseRecordDao.build_transactions_select(user_id),
            RedemptionRecordDao.build_transactions_select(user_id),
        ).subquery()
        result = await query_db.execute(
            select(merged).order_by(merged.c.tx_date, merged.c.source, merged.c.record_id)
        )
        return [cls._transaction_row(row) for row in result.mappings()]

    @staticmethod
    def _transaction_row(row: RowMapping) -> dict:
        """union 行 → 交易记录字段。

        金额口径原样沿用:待确认(所选日期净值未发布)时份额/单价是 0 占位,金额改用录入的
        amount,否则按 份额 × 单价 结算。
        """
        pending = row['status'] == '0'
        shares = float(row['shares'])
        price = float(row['price'])
        amount = row['amount']
        return {
            'type': row['type'],
            # 前端行级删除的定位键:source 区分买卖两侧主键(purchase_id/redemption_id)
            'record_id': row['record_id'],
            'source': row['source'],
            'fund_code': row['fund_code'],
            'fund_name': row['fund_name'],
            'date': row['tx_date'].isoformat(),
            'amount': (
                round(float(amount), 2)
                if pending and amount is not None
                else round(shares * price, 2)
            ),
            'shares': shares,
            'price': price,
            'status': row['status'],
            'remark': row['remark'],
        }

    # ---------- 校验 ----------

    @classmethod
    async def validate_fund_by_code_services(cls, query_db: AsyncSession, fund_code: str) -> ValidationResultModel:
        """验证基金是否存在且启用(持仓添加前置校验)。"""
        errors = []
        fund = await FundDao.get_fund_by_code(query_db, fund_code)
        if not fund:
            errors.append(f'基金代码 {fund_code} 不存在或已删除')
        elif fund.status != '0':
            errors.append(f'基金 {fund.name} 当前为停用状态')
        return ValidationResultModel(valid=len(errors) == 0, errors=errors)

    # ---------- 交易写操作 ----------

    @staticmethod
    async def _guard_duplicate_submission(
        redis: aioredis.Redis,
        user_id: int,
        fund_code: str,
        action: str,
        value,
        tx_date,
    ) -> None:
        """交易写入防重复提交:60s 窗口内同(用户,基金,动作,数值,日期)只放行一次。

        前端按钮的 isPending 禁用在弹窗重开后失效——2026-10-08 实证:净值回源
        慢导致用户重开弹窗连点,一单落了三笔。守卫放在任何写操作与回源之前,
        并发重复在服务端直接拦成 601,不再依赖前端状态。
        """
        key = (
            f'{RedisInitKeyConfig.TX_DUP_GUARD.key}:{user_id}:{fund_code}'
            f':{action}:{tx_date}:{float(value):.2f}'
        )
        granted = await redis.set(key, '1', ex=60, nx=True)
        if not granted:
            raise ServiceWarning(message='检测到重复提交，请稍候再试')

    @classmethod
    async def create_position_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, page_object: PositionCreateModel
    ) -> dict:
        """创建持仓(首次买入):重复检查 → 净值换算份额 → 落库 → 快照回填。"""
        fund = await FundDao.get_fund_by_code(query_db, page_object.fund_code)
        if not fund:
            raise ServiceWarning(message=f'基金代码 {page_object.fund_code} 不存在')
        existing = await PositionDao.get_active_position_by_fund(query_db, user_id, page_object.fund_code)
        if existing:
            raise ServiceWarning(message='该基金已在持仓中，请使用「分批买入」添加')
        await cls._guard_duplicate_submission(
            redis, user_id, page_object.fund_code, 'create', page_object.amount, page_object.purchase_date
        )

        # 会话工厂已设 expire_on_commit=False:落局部变量不是为了防 MissingGreenlet,
        # 而是让后续逻辑与返回 dict 不内嵌 ORM 对象(调用方可能跨事务使用)
        fund_code = fund.code

        # 15:00 之后下单:确认日顺延到下一交易日(撞非交易日由 resolve_target_nav 再顺延);
        # 落库与净值都按**确认日**——与导入侧同一口径(导入件里的日期也是确认日)
        confirm_date = (
            date.fromisoformat(next_confirm_date(page_object.purchase_date))
            if page_object.after_cutoff
            else page_object.purchase_date
        )
        # 净值获取放在任何写操作之前(三级缓存未命中时会 commit 回写,避免污染本事务);
        # 所选日期净值尚未发布(盘中/周末录入)时 resolve 返回 None → 待确认落库,
        # 不回落「取最新值」立即算份额:那会让交易日的买入按上一净值日成交
        resolved = await AkshareService.resolve_target_nav(query_db, redis, fund_code, confirm_date)
        pending = resolved is None
        _, nav = resolved if resolved else ('', 0.0)
        shares = page_object.amount / nav if resolved else 0.0

        try:
            position = UserFundPosition(user_id=user_id, fund_code=page_object.fund_code, status=POSITION_STATUS_NORMAL)
            await PositionDao.add_position_dao(query_db, position)
            position_id = position.position_id
            await PurchaseRecordDao.add_purchase_record_dao(
                query_db,
                PurchaseRecord(
                    position_id=position_id,
                    user_id=user_id,
                    fund_code=page_object.fund_code,
                    shares=shares,
                    cost_price=nav,
                    purchase_date=confirm_date,
                    status='0' if pending else '1',
                    amount=page_object.amount,
                    remark=page_object.remark,
                ),
            )
            await query_db.commit()
            if pending:
                logger.info(
                    f'[持仓] 创建成功(待确认) user_id={user_id} fund_code={fund_code} '
                    f'amount={page_object.amount} 日期={page_object.purchase_date} 净值未发布'
                )
            else:
                logger.info(
                    f'[持仓] 创建成功 user_id={user_id} fund_code={fund_code} '
                    f'amount={page_object.amount} nav={nav} shares={shares:.4f}'
                )
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[持仓] 创建失败回滚 user_id={user_id} fund_code={page_object.fund_code} | {e}')
            raise e

        if not pending:
            await SnapshotService.update_snapshots_for_transaction_services(query_db, redis, user_id, page_object.purchase_date)

        detail = await cls.get_position_detail_services(query_db, redis, position_id, user_id)
        if detail is not None and pending:
            # 待确认标记:前端据此提示「净值公布后自动确认份额」
            detail['pendingConfirm'] = True
        return detail or {}

    @classmethod
    async def add_purchase_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, page_object: PurchaseRecordCreateModel
    ) -> dict:
        """分批买入(无 active 持仓时自动建仓)。"""
        fund = await FundDao.get_fund_by_code(query_db, page_object.fund_code)
        if not fund:
            raise ServiceWarning(message=f'基金代码 {page_object.fund_code} 不存在')
        await cls._guard_duplicate_submission(
            redis, user_id, page_object.fund_code, 'purchase', page_object.amount, page_object.purchase_date
        )

        # 会话工厂已设 expire_on_commit=False:落局部变量不是为了防 MissingGreenlet,
        # 而是让后续逻辑与返回 dict 不内嵌 ORM 对象(调用方可能跨事务使用)
        fund_code = fund.code

        # 15:00 之后下单:确认日顺延到下一交易日(详见 create_position_services 同款注释)
        confirm_date = (
            date.fromisoformat(next_confirm_date(page_object.purchase_date))
            if page_object.after_cutoff
            else page_object.purchase_date
        )
        # 所选日期净值尚未发布 → 待确认落库(shares=0 不计入汇总),发布后由读取路径懒确认
        resolved = await AkshareService.resolve_target_nav(query_db, redis, fund_code, confirm_date)
        pending = resolved is None
        _, nav = resolved if resolved else ('', 0.0)
        shares = page_object.amount / nav if resolved else 0.0

        try:
            position = await PositionDao.get_active_position_by_fund(query_db, user_id, page_object.fund_code)
            if not position:
                position = UserFundPosition(user_id=user_id, fund_code=page_object.fund_code, status=POSITION_STATUS_NORMAL)
                await PositionDao.add_position_dao(query_db, position)
            record = await PurchaseRecordDao.add_purchase_record_dao(
                query_db,
                PurchaseRecord(
                    position_id=position.position_id,
                    user_id=user_id,
                    fund_code=fund_code,
                    shares=shares,
                    cost_price=nav,
                    purchase_date=confirm_date,
                    status='0' if pending else '1',
                    amount=page_object.amount,
                    remark=page_object.remark,
                ),
            )
            # 返回 dict 在 commit 前拼好:record 的属性 commit 后会过期
            purchase = {
                'purchase_id': record.purchase_id,
                'position_id': record.position_id,
                'shares': float(record.shares),
                'cost_price': float(record.cost_price),
                'purchase_date': record.purchase_date,
                'total_cost': float(record.shares) * float(record.cost_price),
                'status': record.status,
                'amount': float(page_object.amount),
                'create_time': record.create_time,
                'remark': record.remark,
            }
            await query_db.commit()
            if pending:
                logger.info(f'[持仓] 买入成功(待确认) user_id={user_id} fund_code={fund_code} amount={page_object.amount} 净值未发布')
            else:
                logger.info(f'[持仓] 买入成功 user_id={user_id} fund_code={fund_code} amount={page_object.amount} shares={shares:.4f}')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[持仓] 买入失败回滚 user_id={user_id} fund_code={page_object.fund_code} | {e}')
            raise e

        if not pending:
            await SnapshotService.update_snapshots_for_transaction_services(query_db, redis, user_id, page_object.purchase_date)
        result = CamelCaseUtil.transform_result(purchase)
        if pending:
            result['pendingConfirm'] = True
        return result

    @classmethod
    async def add_redemption_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, page_object: RedemptionRecordCreateModel
    ) -> dict:
        """赎回:防御性校验(份额/日期)→ 净值换算 → 落库 → 快照回填 → 全额赎回软删。

        软删必须放在快照生成之后——赎回当日份额仍参与波动。
        """
        fund = await FundDao.get_fund_by_code(query_db, page_object.fund_code)
        if not fund:
            raise ServiceWarning(message=f'基金代码 {page_object.fund_code} 不存在')
        position = await PositionDao.get_active_position_by_fund(query_db, user_id, page_object.fund_code)
        if not position:
            raise ServiceWarning(message='该基金没有有效持仓')

        # 会话工厂已设 expire_on_commit=False:落局部变量不是为了防 MissingGreenlet,
        # 而是让后续逻辑与返回 dict 不内嵌 ORM 对象(调用方可能跨事务使用)
        fund_code = fund.code
        position_id = position.position_id

        purchases = await PurchaseRecordDao.get_purchase_records(query_db, position_id)
        redemptions = await RedemptionRecordDao.get_redemption_records(query_db, position_id)
        remaining_shares = sum(float(p.shares) for p in purchases) - sum(float(r.shares) for r in redemptions)
        if page_object.shares > remaining_shares:
            raise ServiceWarning(message=f'赎回份额 {page_object.shares} 超过持有份额 {remaining_shares:.4f}')
        await cls._guard_duplicate_submission(
            redis, user_id, page_object.fund_code, 'redemption', page_object.shares, page_object.redemption_date
        )

        # 15:00 之后下单:确认日顺延到下一交易日(影响到账金额与快照里份额扣减的日期)
        confirm_date = (
            date.fromisoformat(next_confirm_date(page_object.redemption_date))
            if page_object.after_cutoff
            else page_object.redemption_date
        )
        earliest_date = min(p.purchase_date for p in purchases)
        # 校验拿顺延后的确认日比:15:00 后下单本就不可能早于首次买入的确认日
        if confirm_date < earliest_date:
            raise ServiceWarning(message=f'赎回确认日 {confirm_date} 早于首次买入日期 {earliest_date}')

        # 时间线校验(总量校验不够):回溯录入可按「大额先录」的顺序绕过总量校验,
        # 最终形成 Σ赎回 > Σ买入 的超赎数据(2026-10-08 实证:四笔赎回合计 2000 > 买入 1200,
        # 份额时间线变负,市值/收益率曲线全线崩坏)。把本笔插入流水后,成交日当日起
        # 逐个流水检查点的份额不得为负。
        _buy_pairs = [(p.purchase_date, float(p.shares)) for p in purchases]
        _red_pairs = [(r.redemption_date, float(r.shares)) for r in redemptions]
        _new_red_pairs = _red_pairs + [(confirm_date, float(page_object.shares))]
        _checkpoints = sorted({d for d, _ in _new_red_pairs if d >= confirm_date})
        for _d in _checkpoints:
            _held = shares_held_on_pairs(_buy_pairs, _new_red_pairs, _d)
            if _held < -SHARES_ZERO_EPSILON:
                raise ServiceWarning(
                    message=(
                        f'赎回份额 {page_object.shares} 超过 {confirm_date} 时点的持有份额，'
                        f'按成交日时间线该日仅持有 {max(_held, 0.0):.4f} 份'
                    )
                )

        # 赎回的份额扣减/全额判定照旧(赎回当日仍参与波动——T+1 口径已有);
        # 待确认只影响到账金额(nav_price/amount),不影响份额体系
        resolved = await AkshareService.resolve_target_nav(query_db, redis, fund_code, confirm_date)
        pending = resolved is None
        _, nav = resolved if resolved else ('', 0.0)

        # 赎回到账金额:普通基金 = 份额 × 赎回净值;货币基金按日结转,真实到账含
        # 每日结转收益 → 按份额比例分摊赎回日的复利市值(nav_price 仍落 1.0 供
        # 成本结转口径)。若 amount 也按 1.0 落库,已实现盈亏恒为 0
        # (2026-10-08 用户发现)。分母 remaining_shares 即赎回前持有份额(日收益族)。
        # **赎回前移一日**(2026-10-22,与持仓摘要同款修正):held_value 用的
        # redemptions 含当日早前的赎回,但市值族"次日才扣"——当日第二笔赎回的
        # 分摊基数仍是满份额市值,到账金额被多算(实证:000198 当日先赎 200 再赎
        # 100,第二笔 amount=120.59 而非 100.49,已实现盈亏凭空多 20.59)。
        # 赎回日期前移一日让当日早前的赎回即时生效,held_value 与
        # remaining_shares 同口径。
        redeem_amount = page_object.shares * nav
        if await AkshareService.is_money_fund(query_db, fund_code):
            money_series = await AkshareService.get_money_fund_nav_series(query_db, redis, fund_code)
            if money_series and remaining_shares > 1e-6:
                held_value = money_market_value_on(
                    [(p.purchase_date, float(p.shares)) for p in purchases],
                    [(r.redemption_date - timedelta(days=1), float(r.shares)) for r in redemptions],
                    MoneyAccumCurve(money_series),
                    confirm_date,
                )
                redeem_amount = page_object.shares / remaining_shares * held_value

        remaining_after = remaining_shares - page_object.shares
        try:
            record = await RedemptionRecordDao.add_redemption_record_dao(
                query_db,
                RedemptionRecord(
                    position_id=position_id,
                    user_id=user_id,
                    fund_code=fund_code,
                    shares=page_object.shares,
                    nav_price=nav,
                    redemption_date=confirm_date,
                    status='0' if pending else '1',
                    amount=None if pending else redeem_amount,
                    remark=page_object.remark,
                ),
            )
            # 返回 dict 在 commit 前拼好:record 的属性 commit 后会过期
            redemption = {
                'redemption_id': record.redemption_id,
                'position_id': record.position_id,
                'shares': float(record.shares),
                'nav_price': float(record.nav_price),
                'redemption_date': record.redemption_date,
                'total_amount': float(record.shares) * float(record.nav_price),
                'status': record.status,
                'create_time': record.create_time,
                'remark': record.remark,
            }
            if remaining_after <= FULL_REDEMPTION_TOLERANCE:
                position.status = POSITION_STATUS_FULLY_REDEEMED
            await query_db.commit()
            if pending:
                logger.info(
                    f'[持仓] 赎回成功(待确认) user_id={user_id} fund_code={fund_code} '
                    f'shares={page_object.shares} 净值未发布 remaining={remaining_after:.4f}'
                )
            else:
                logger.info(
                    f'[持仓] 赎回成功 user_id={user_id} fund_code={fund_code} '
                    f'shares={page_object.shares} nav={nav} remaining={remaining_after:.4f}'
                )
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[持仓] 赎回失败回滚 user_id={user_id} fund_code={page_object.fund_code} | {e}')
            raise e

        # 待确认赎回的份额照常参与波动,快照回填不依赖净值已发布,照旧执行
        await SnapshotService.update_snapshots_for_transaction_services(query_db, redis, user_id, page_object.redemption_date)

        # 快照生成后再软删除(交易记录保留,历史快照完整)
        if remaining_after <= FULL_REDEMPTION_TOLERANCE:
            try:
                await PositionDao.delete_position_dao(query_db, position_id, None, datetime.now())
                await query_db.commit()
            except Exception as e:
                await query_db.rollback()
                logger.error(f'[持仓] 全额赎回软删失败 position_id={position_id} | {e}')
                raise e

        result = CamelCaseUtil.transform_result(redemption)
        if pending:
            result['pendingConfirm'] = True
        return result

    @classmethod
    async def delete_position_services(cls, query_db: AsyncSession, position_id: int, user_id: int) -> None:
        """手动软删除持仓(行级归属校验)。"""
        position = await PositionDao.get_position_by_id(query_db, position_id, user_id)
        if not position:
            raise ServiceWarning(message='持仓不存在')
        try:
            await PositionDao.delete_position_dao(query_db, position_id, None, datetime.now())
            await query_db.commit()
            logger.info(f'[持仓] 手动删除 position_id={position_id} user_id={user_id}')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[持仓] 删除失败回滚 position_id={position_id} | {e}')
            raise e

    @classmethod
    async def delete_transaction_services(
        cls,
        query_db: AsyncSession,
        user_id: int,
        tx_type: str,
        record_id: int,
    ) -> bool:
        """单条硬删除买入/赎回记录(tx_type 取 'purchase'/'redemption'),返回是否真的删了。

        幂等:记录不存在(重复删除/列表未及时刷新)返回 False 而非报错。

        流水是份额与快照的唯一来源,删除后的一致性处理:
        - 持仓头表是流水聚合派生,派生值自动回正;但两种边界要手工收口——
          ①记录删光后头表成无源空壳 → 物理删除;②全额赎回软删的头表,
          删掉赎回记录使剩余份额回到正数 → 复活(del_flag 置回 '0');
        - 快照/现金流是预计算结果,不感知删除 → **由 controller 在响应后以后台任务
          全量重建**(rebuild_from_transactions 先清空再重算,消失基金的快照一并清除;
          实测 5~98 秒,同步执行会把删除接口拖成几十秒,诱发重复点击)。
        删掉的记录重新导入会被判为新数据——「删错了再导回来」正是期望行为。
        """
        dao = (
            PurchaseRecordDao if tx_type == 'purchase'
            else RedemptionRecordDao if tx_type == 'redemption'
            else None
        )
        if dao is None:
            raise ServiceWarning(message=f'未知交易类型 {tx_type}')
        record = await dao.get_record_by_id_for_user(query_db, record_id, user_id)
        if not record:
            # 幂等:列表未及时刷新时的重复删除按「已删除」成功处理(返回 False,不触发快照重建)。
            # 此前抛 601「交易记录不存在」:删除响应被快照重建拖住 5~98 秒,用户以为没删掉
            # 再点一次,撞上这句产生误导性错误 toast——而记录其实早已删掉
            logger.info(f'[持仓] 删除交易记录:记录不存在或已删除 user_id={user_id} type={tx_type} record_id={record_id}')
            return False
        try:
            await dao.delete_record_dao(query_db, record)
            purchases = await PurchaseRecordDao.get_purchase_records(query_db, record.position_id)
            redemptions = await RedemptionRecordDao.get_redemption_records(query_db, record.position_id)
            position = await PositionDao.get_any_position_by_id(query_db, record.position_id, user_id)
            if position:
                if not purchases and not redemptions:
                    await PositionDao.delete_position_physical_dao(query_db, position)
                else:
                    remaining = sum(float(p.shares) for p in purchases) - sum(
                        float(r.shares) for r in redemptions
                    )
                    # 删除买入可能使剩余份额变负(其后的赎回建立在这笔买入之上):
                    # 派生份额为负是非法状态,须整单拒绝并指路,而不是让脏数据进库
                    if tx_type == 'purchase' and remaining < -1e-6:
                        raise ServiceWarning(
                            message=(
                                f'删除该买入记录将使 {record.fund_code} 的剩余份额变为 '
                                f'{remaining:.4f}(其后的赎回建立在这笔买入之上)，'
                                f'请先删除对应的赎回记录'
                            )
                        )
                    if position.del_flag != '0' and remaining > 1e-6:
                        await PositionDao.revive_position_dao(query_db, record.position_id)
            await query_db.commit()
            logger.info(
                f'[持仓] 删除交易记录 user_id={user_id} type={tx_type} '
                f'record_id={record_id} fund_code={record.fund_code}'
            )
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[持仓] 删除交易记录失败回滚 user_id={user_id} record_id={record_id} | {e}')
            raise e

        # 快照重建已移出请求(见 controller 的 BackgroundTasks):全量重建实测 5~98 秒,
        # 同步执行会把删除接口拖成几十秒,期间列表不刷新诱发重复点击
        return True

    @classmethod
    async def delete_all_transactions_services(cls, query_db: AsyncSession, user_id: int) -> dict:
        """一级:清空全部买卖流水,连带清空持仓与快照/现金流(不可恢复)。

        流水是份额与快照的唯一来源:它没了,持仓就是无源空壳、快照是无法重建的假数据,
        故整条链必须一起清。全程单事务——不允许出现「流水删了而快照还在」的中间态。

        流水直接按 user_id 删(2026-09-21 起流水表自带账号):不必再经持仓定位,
        因此「先清空持仓、再清空流水」这条路径上残留的流水也能一并清掉。
        """
        try:
            cleared = await SnapshotService.clear_snapshots_and_cash_flows(query_db, user_id)
            purchases_deleted = await PurchaseRecordDao.delete_all_for_user(query_db, user_id)
            redemptions_deleted = await RedemptionRecordDao.delete_all_for_user(query_db, user_id)
            positions_deleted = await PositionDao.delete_all_positions_for_user(query_db, user_id)
            await query_db.commit()
            logger.info(
                f'[持仓] 清空全部流水 user_id={user_id} 持仓={positions_deleted} '
                f'买入={purchases_deleted} 赎回={redemptions_deleted} | {cleared}'
            )
            # 条数要进前端 toast,契约与其它接口一致走驼峰
            return CamelCaseUtil.transform_result({
                **cleared,
                'positions_deleted': positions_deleted,
                'purchases_deleted': purchases_deleted,
                'redemptions_deleted': redemptions_deleted,
            })
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[持仓] 清空全部流水失败回滚 user_id={user_id} | {e}')
            raise e

    @classmethod
    async def delete_all_positions_services(cls, query_db: AsyncSession, user_id: int) -> dict:
        """二级:清空全部持仓,连带清空快照/现金流;买卖流水保留。

        流水留着才能继续追溯已实现收益与累计投入——明细按 fund_code 查询,
        持仓行没了也不影响流水可读性。留着空壳持仓没有意义,故物理删而非软删。
        """
        try:
            cleared = await SnapshotService.clear_snapshots_and_cash_flows(query_db, user_id)
            positions_deleted = await PositionDao.delete_all_positions_for_user(query_db, user_id)
            await query_db.commit()
            logger.info(f'[持仓] 清空全部持仓 user_id={user_id} 持仓={positions_deleted} | {cleared}')
            # 条数要进前端 toast,契约与其它接口一致走驼峰
            return CamelCaseUtil.transform_result({**cleared, 'positions_deleted': positions_deleted})
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[持仓] 清空全部持仓失败回滚 user_id={user_id} | {e}')
            raise e

    # ---------- 历史持仓 ----------

    @classmethod
    async def get_position_at_date_services(
        cls,
        query_db: AsyncSession,
        redis: aioredis.Redis,
        position_id: int,
        user_id: int,
        query_date: date,
        *,
        confirm_pending: bool = False,
    ) -> dict | None:
        """获取指定日期的持仓快照(历史份额/历史成本,收益率计算基础)。

        confirm_pending 默认关闭:分析链路按「日期 × 持仓」反复调用本方法,逐次触发
        待确认回填会带出大量冗余查询与中途 commit;回填交给读取路径(持仓列表/明细)负责。
        """
        current = await cls.get_position_detail_services(
            query_db, redis, position_id, user_id, confirm_pending=confirm_pending
        )
        if not current:
            return None
        # 关联键早已从 fund_id 切到 fund_code(明细不再返回 fundId),此处曾残留 current['fundId'] → KeyError
        fund = await FundDao.get_fund_by_code(query_db, current['fundCode'])
        if not fund:
            return None

        all_purchases = await PurchaseRecordDao.get_purchase_records(query_db, position_id)
        all_redemptions = await RedemptionRecordDao.get_redemption_records(query_db, position_id)
        purchases_before = [p for p in all_purchases if p.purchase_date <= query_date]

        # 份额与净值均走公共工具:历史持仓取「该日收盘后」口径,与本次重构前的行为等价
        historical_shares = shares_held_at_close(all_purchases, all_redemptions, query_date)
        nav_records = await AkshareService.get_fund_nav(query_db, redis, fund.code)
        nav_on_date = nav_at_or_before(nav_records, query_date)
        if nav_on_date is None:
            return None

        # 历史成本同样要扣掉此前已卖出份额的成本(2026-09-22 与持仓明细同步修):
        # 旧实现 = 该日之前全部买入金额,已卖掉的部分仍压在成本上,历史收益率同样被放大
        _, cost_at_date, _ = cost_basis_walk(
            [(p.purchase_date, p.shares, purchase_amount(p)) for p in purchases_before],
            [
                (r.redemption_date, r.shares, r.nav_price)
                for r in all_redemptions
                if r.redemption_date <= query_date
            ],
        )
        historical_value = historical_shares * nav_on_date

        result = dict(current)
        result.update({
            'totalShares': historical_shares,
            'totalCost': cost_at_date,
            'avgCostPrice': cost_at_date / historical_shares if historical_shares > 0 else 0,
            'currentValue': historical_value,
            'profit': historical_value - cost_at_date,
            'profitRate': (historical_value - cost_at_date) / cost_at_date * 100 if cost_at_date > 0 else 0,
        })
        return result
