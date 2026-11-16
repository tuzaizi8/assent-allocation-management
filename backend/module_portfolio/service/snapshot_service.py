"""持仓快照 Service(业务逻辑层)。

职责:每日持仓快照与现金流水的生成/回填/重建。
快照份额规则:买入 <= 当日计入,赎回 < 次日才扣除(赎回当日仍参与波动,T+1 语义)。
"""

import asyncio
import time
from collections import defaultdict
from datetime import date, timedelta

from redis import asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from common.response import PageModel
from exceptions.exceptions import ServiceWarning
from module_fund.dao.fund_dao import FundDao
from module_fund.service.akshare_service import AkshareService
from module_portfolio.dao.daily_cash_flow_dao import DailyCashFlowDao
from module_portfolio.dao.daily_snapshot_dao import DailySnapshotDao
from module_portfolio.dao.position_dao import PositionDao
from module_portfolio.dao.purchase_record_dao import PurchaseRecordDao
from module_portfolio.dao.redemption_record_dao import RedemptionRecordDao
from module_portfolio.service.position_calc_util import (
    filter_effective_records,
    is_snapshot_nav_stale,
    MoneyAccumCurve,
    money_market_value_on,
    nav_at_or_before,
    purchase_amount,
    redemption_amount,
    shares_held_on_pairs,
)
from utils.camel_case_util import CamelCaseUtil
from utils.log import logger

# 读路径懒补的冷却键:同一用户 10 分钟内最多重建一次(挡多标签页/并发请求)。
# TTL 取 10 分钟而非「顶到下一个净值窗口」:22:05 首次访问时当日净值可能还没发布,
# 10 分钟后(净值已出)再访问即可补上,不必干等到次日。
SNAPSHOT_REBUILD_LOCK_KEY = 'snapshot:rebuild_lock'
SNAPSHOT_REBUILD_LOCK_TTL = 600

# 读路径懒补的区间回看天数:净值「事后修正/发布滞后」通常只涉及最近几天,而 `is_snapshot_nav_stale`
# 只比对「最新快照日」那一行——只补那一天会漏掉同窗口内其它天用旧净值写下的行(2026-09-19 实测:
# 09-13 有 21 行仍写着更早的净值,1 天窗口修不到)。回看 7 天的规模实测 217 行 / 约 125ms,
# 仍远低于全量重建的 42897 行 / 5.2 秒。
LAZY_REFRESH_LOOKBACK_DAYS = 7

# 快照/现金流写入的互斥锁命名空间(pg_advisory_xact_lock 的第一个入参,int4)。
# 全库仅此一处使用 advisory lock,固定值即可;改值等价于换一把锁,不影响正确性。
SNAPSHOT_WRITE_LOCK_NS = 20260918


def plan_prune_pairs(
    pairs_by_fund: dict[str, tuple[list[tuple[date, float]], list[tuple[date, float]]]],
    keep_pairs: set[tuple[date, str]],
    start_date: date,
    end_date: date,
) -> list[tuple[date, str]]:
    """算出区间里该删掉的快照行:按流水明确份额<=0、且本轮没有算出来的 (日期,基金)。

    只做「正向可判定才删」:份额由买卖流水算出,份额>0 的基金**即使因为取不到净值被
    `_build_snapshot_rows` 跳过**(不在 keep_pairs 里),也不会进删除集——否则会把"暂时缺净值"
    的行误删(残缺数据的镜像陷阱)。抽成纯函数,便于不经数据库单测。
    """
    zero_share_pairs: set[tuple[date, str]] = set()
    current = start_date
    while current <= end_date:
        for fund_code, (purchases, redemptions) in pairs_by_fund.items():
            if shares_held_on_pairs(purchases, redemptions, current) <= 0:
                zero_share_pairs.add((current, fund_code))
        current += timedelta(days=1)
    return sorted(zero_share_pairs - keep_pairs)


class SnapshotService:
    """每日快照与现金流服务。"""

    @classmethod
    async def ensure_fresh_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int
    ) -> bool:
        """读路径懒补:快照落后于当前可用净值时静默增量补「最新快照日~今天」,返回是否真的补过。

        快照只在「交易后回填」与「手动生成/重建」两处写入,没有定时任务;而净值当晚才发布、
        个别基金还会滞后一两天。不补的话当日市值会沿用上一根净值(当日收益恒为 0),或长期
        停在更早的旧根上(见 `is_snapshot_nav_stale` 的两条判定)。这里把这件事收敛成读路径
        上的一个关卡:判定走纯函数,执行只补尾部区间。

        为什么不整段重算:`is_snapshot_nav_stale` 只比对库中「最新快照日」那一行,它两条判据
        (同日净值被修正、可用净值已延伸到更晚交易日)发现的滞后都落在 `[最新快照日, 今天]`,
        区间外的历史与判定无关;现金流侧 `_build_cash_flow_rows` 已把区间前的历史交易先累计进
        净投入,尾部行与全量重算逐行一致。因此几万行的「清空+重写」可降为百行级 upsert。
        全量重建仍保留给三个入口:手动重建按钮、交易确认后、导入确认后——补一笔很久以前的交易
        会改变其后所有日期的份额与累计投入,那是全量语义。

        纪律:任何异常都吞掉并回滚(补数失败不能拖垮读路径),只留 warning;只有**本次真的抢到**
        冷却键才会释放它——否则会把并发请求正在用的冷却窗口误删,放进第二个写入。
        调用约束:调用方在同一 session 上**不得有未提交的写**(兜底会 rollback 整个 session)。
        """
        locked = False
        try:
            latest_date = await DailySnapshotDao.get_latest_snapshot_date(query_db, user_id)
            if latest_date is None:
                # 没有快照:交给交易回填与手动生成,不在读路径凭空造历史
                return False
            last_rows = await DailySnapshotDao.get_snapshots_in_range(
                query_db, user_id, latest_date, latest_date
            )
            snapshot_navs = {row.fund_code: float(row.nav) for row in last_rows}
            if not snapshot_navs:
                return False
            # 只判「快照里那几只基金」的净值:已清仓(份额归零)的基金不在快照里,其净值更新不该触发重建
            nav_cache = await cls._prefetch_nav_records(query_db, redis, set(snapshot_navs))
            if not is_snapshot_nav_stale(latest_date, snapshot_navs, nav_cache):
                return False
            if not await cls._acquire_rebuild_lock(redis, user_id):
                return False
            locked = True
            today = date.today()
            # 区间起点取「最新快照日」与「今天往前回看 7 天」中更早者:既保证 latest 之后的缺口不漏,
            # 又能自愈最近一周的净值修正(见 LAZY_REFRESH_LOOKBACK_DAYS 注释)
            start_date = min(latest_date, today - timedelta(days=LAZY_REFRESH_LOOKBACK_DAYS - 1))
            # nav_cache 复用判定阶段已取回的净值,不再为同一批基金预取第二遍
            await cls._refresh_range_services(
                query_db, redis, user_id, start_date, today, nav_cache=nav_cache
            )
            logger.info(
                f'[快照] 读路径懒补完成(增量) user_id={user_id} 区间={start_date.isoformat()}~{today.isoformat()} '
                f'基金数={len(snapshot_navs)}'
            )
            return True
        except ServiceWarning as e:
            # 另有写入正在进行(DB 写锁被占):本次虽抢到了冷却键也保留它——占锁者可能根本不走冷却键
            # (清空接口),留着能避免读路径在它跑完前反复重试
            await query_db.rollback()
            logger.info(f'[快照] 读路径懒补跳过(已有写入在进行) user_id={user_id} | {e}')
            return False
        except Exception as e:
            await query_db.rollback()
            if locked:
                # 失败后释放冷却键,让下次访问还能重试;没抢到就别动别人的键
                await cls._release_rebuild_lock(redis, user_id)
            logger.warning(f'[快照] 读路径懒补失败 user_id={user_id} | {e}')
            return False

    @classmethod
    async def _acquire_rebuild_lock(cls, redis: aioredis.Redis, user_id: int) -> bool:
        """抢冷却键(set NX):拿到即允许重建,拿不到说明本冷却窗口内已经补过。

        值存**加锁时刻的时间戳**:冷却键被占时据此判断"上次重建是多久以前",日志里能说清是
        "刚跑过"还是"正在跑"(配合 `_try_lock_user_writes` 的探测)。
        """
        return bool(
            await redis.set(
                f'{SNAPSHOT_REBUILD_LOCK_KEY}:{user_id}',
                str(int(time.time())),
                ex=SNAPSHOT_REBUILD_LOCK_TTL,
                nx=True,
            )
        )

    @classmethod
    async def _release_rebuild_lock(cls, redis: aioredis.Redis, user_id: int) -> None:
        """释放冷却键:重建失败时若不释放,用户要白等一个冷却窗口才可能补上。"""
        try:
            await redis.delete(f'{SNAPSHOT_REBUILD_LOCK_KEY}:{user_id}')
        except Exception:
            # 释放失败只影响重试时机,不能盖住重建本身的异常
            pass

    @classmethod
    async def _try_lock_user_writes(cls, query_db: AsyncSession, user_id: int) -> bool:
        """抢「该用户快照/现金流写入」的事务级互斥锁:拿到返回 True,同用户已有写入在进行返回 False。

        用 pg_advisory_xact_lock 的 try 版:随 COMMIT / ROLLBACK / 连接断开自动释放,无需手工解锁,
        天然覆盖多进程与多容器;try 版不阻塞——单次重建耗时 60~100 秒,阻塞会把读请求与工作线程
        久挂,并发时正确语义是「只有一个成功」。

        纪律:锁必须抢在「即将写入并提交的那个事务」内、清空/写入之前。抢早了会被中途的 commit
        (如净值回源)提前放掉,互斥形同虚设;同一事务内重复抢同一把锁是可重入的,不会自锁。

        依赖默认隔离级别 READ COMMITTED:锁内「先查再插」能看到上一个持锁者已提交的行。若将来
        把连接改成 REPEATABLE READ,事务快照可能早于抢锁点(读到旧数据)而撞唯一约束,需一并复查。
        """
        result = await query_db.execute(
            text('SELECT pg_try_advisory_xact_lock(:ns, :user_id)'),
            {'ns': SNAPSHOT_WRITE_LOCK_NS, 'user_id': user_id},
        )
        return bool(result.scalar())

    @classmethod
    async def get_snapshot_daily_page_services(
        cls,
        query_db: AsyncSession,
        redis: aioredis.Redis,
        user_id: int,
        start_date: date | None,
        end_date: date,
        page_num: int,
        page_size: int,
    ) -> PageModel:
        """按日聚合分页(历史持仓页明细表);聚合与分页在 DAO,本层只透传。

        start_date 为 None 即查全部历史(2026-10-12 起 90 天默认限制取消)。
        先过一遍懒补:本表首行就是「最新快照日」,是用户判断快照是否滞后的第一现场。
        """
        await cls.ensure_fresh_services(query_db, redis, user_id)
        return await DailySnapshotDao.get_snapshot_daily_page(
            query_db, user_id, start_date, end_date, page_num, page_size
        )

    @classmethod
    async def get_snapshot_day_detail_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, day: date
    ) -> dict:
        """某日的基金明细(每日持仓页行点击抽屉);占比在本层算好,前端不重算。

        与按日聚合列表同源:同走懒补,保证「最新一天点开也不会缺行」。
        """
        await cls.ensure_fresh_services(query_db, redis, user_id)
        rows = await DailySnapshotDao.get_snapshots_for_day(query_db, user_id, day)
        total = sum(r['market_value'] for r in rows)
        # 手工 dict 不走 CamelCaseUtil,键直接写驼峰与前端契约对齐
        # (实证 2026-10-12:返回 snake_case 键,前端读 marketValue 得 undefined 崩抽屉)
        funds = [
            {
                'fundCode': r['fund_code'],
                'fundName': r['fund_name'],
                'shares': r['shares'],
                'nav': r['nav'],
                'marketValue': r['market_value'],
                'ratio': round(r['market_value'] / total * 100, 2) if total > 0 else 0.0,
            }
            for r in rows
        ]
        return {
            'snapshotDate': day.isoformat(),
            'totalValue': round(total, 2),
            'fundCount': len(funds),
            'funds': funds,
        }

    @classmethod
    async def get_quarterly_snapshots_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int
    ) -> dict:
        """全部季度末的持仓快照(历史持仓页季度变化卡片的数据源)。

        范围从「用户最远快照日所在季度末」到当前季度末(2026-10-12 用户裁决:
        不再固定 8 季,最远由每人自己的快照决定,如最远 2021-03-18 → 最远季度
        2021-03-31)。季度末常撞周末或未生成,取 ≤ 季度末的最近快照日;占比与
        总市值在本层算好(驼峰键,手工 dict 契约)。相邻季度的变化对比(新增/
        加减仓)由前端按 fund_code 匹配计算,后端只交付干净的季度序列。
        """
        await cls.ensure_fresh_services(query_db, redis, user_id)
        today = date.today()
        # 最远快照日 → 所在季度的季度末(如 2021-03-18 → 2021-03-31);无快照直接空
        first_date = await DailySnapshotDao.get_earliest_snapshot_date(query_db, user_id)
        if first_date is None:
            return {'quarters': []}
        quarter_ends: list[date] = []
        # 起始季度末 = 最远快照日所在季度(月 1-3 → 3-31,4-6 → 6-30,7-9 → 9-30,10-12 → 12-31)
        year, month = first_date.year, ((first_date.month - 1) // 3) * 3 + 3
        while True:
            qe = date(year, month, {3: 31, 6: 30, 9: 30, 12: 31}[month])
            if qe > today:
                break
            quarter_ends.append(qe)
            month += 3
            if month > 12:
                month -= 12
                year += 1

        result = []
        for qe in quarter_ends:
            sd = await DailySnapshotDao.get_latest_snapshot_date_on_or_before(
                query_db, user_id, qe
            )
            if sd is None:
                continue
            rows = await DailySnapshotDao.get_snapshots_for_day(query_db, user_id, sd)
            total = sum(r['market_value'] for r in rows)
            result.append(
                {
                    'quarterEnd': qe.isoformat(),
                    'snapshotDate': sd.isoformat(),
                    'totalValue': round(total, 2),
                    'funds': [
                        {
                            'fundCode': r['fund_code'],
                            'fundName': r['fund_name'],
                            'fundType': r['fund_type'],
                            'marketValue': r['market_value'],
                            'ratio': round(r['market_value'] / total * 100, 2)
                            if total > 0
                            else 0.0,
                        }
                        for r in rows
                    ],
                }
            )
        return {'quarters': result}

    @classmethod
    async def _prefetch_nav_records(
        cls, query_db: AsyncSession, redis: aioredis.Redis, fund_codes: set[str]
    ) -> dict[str, list[dict]]:
        """预取基金净值(循环外一次拉齐,避免逐日重复触发三级缓存)。"""
        nav_cache: dict[str, list[dict]] = {}
        for code in fund_codes:
            nav_cache[code] = await AkshareService.get_fund_nav(query_db, redis, code)
        return nav_cache

    @classmethod
    def _build_money_curves(
        cls, funds: dict, nav_cache: dict[str, list[dict]]
    ) -> dict[str, MoneyAccumCurve]:
        """从已取回的合成净值序列构造货币基金市值曲线,供 _build_snapshot_rows 使用。

        **所有快照写入路径(区间生成/增量懒补/交易后回填/全量重建)都必须传入**——
        漏传的路径会把货基行写成 份额×1.0,与已入库的复利市值断层,
        收益率曲线在写入边界跳水(2026-10-08 实证事故:第二笔买入触发交易后回填,
        尾部行全部退化,约 54 元已赚收益从曲线上消失)。

        合成序列为空(回源失败/数据缺失)时**仍要建曲线**(MoneyAccumCurve 空曲线
        的 accum_at 恒 1.0)——市值退化为名义份额本金,行不缺失;若因此跳过货基,
        清空重写模式下整只基金从快照里蒸发,市值曲线断崖(2026-10-08 第二例:
        001820 回源瞬断,2500 份活跃持仓从曲线消失)。
        """
        return {
            code: MoneyAccumCurve(nav_cache.get(code) or [])
            for code, fund in funds.items()
            if AkshareService.is_money_fund_type(fund.fund_type)
        }

    @classmethod
    async def _get_funds_by_positions(cls, query_db: AsyncSession, positions: list) -> dict:
        """按持仓集合装配基金映射(fund_code → Fund)。"""
        fund_codes = {pos.fund_code for pos in positions}
        funds = {}
        for code in fund_codes:
            fund = await FundDao.get_fund_by_code(query_db, code)
            if fund:
                funds[code] = fund
        return funds

    @classmethod
    async def clear_snapshots_and_cash_flows(cls, query_db: AsyncSession, user_id: int) -> dict:
        """清空该用户的快照与现金流(只 flush,提交时机由调用方决定)。

        级联删除要把它和「删持仓/删流水」放在同一个事务里,故对外公开且不自行提交。
        互斥:清空(先删后由调用方提交)与并发重建同样会交错成重复数据,故与重建共用同一把事务级锁;
        重建内部再调本方法属同事务重复抢锁,advisory lock 可重入,不会自锁。
        """
        if not await cls._try_lock_user_writes(query_db, user_id):
            logger.warning(f'[快照] 已有写入在进行,拒绝清空快照/现金流 user_id={user_id}')
            raise ServiceWarning(message='已有重建正在进行，请稍后再试')
        return {
            'snapshots_deleted': await DailySnapshotDao.delete_all_snapshots_for_user(query_db, user_id),
            'cash_flows_deleted': await DailyCashFlowDao.delete_all_cash_flows_for_user(query_db, user_id),
        }

    @classmethod
    async def delete_all_snapshots_services(cls, query_db: AsyncSession, user_id: int) -> dict:
        """三级:只清空快照与现金流(交易与持仓不动,可随时重新生成)。"""
        try:
            cleared = await cls.clear_snapshots_and_cash_flows(query_db, user_id)
            await query_db.commit()
            logger.info(f'[快照] 清空快照与现金流 user_id={user_id} | {cleared}')
            # 条数要进前端 toast,契约与其它接口一致走驼峰
            return CamelCaseUtil.transform_result(cleared)
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[快照] 清空失败回滚 user_id={user_id} | {e}')
            raise e

    @classmethod
    async def _collect_position_data(
        cls,
        query_db: AsyncSession,
        positions: list,
        fund_codes: set[str],
        *,
        snapshot_position_ids: set[int] | None = None,
        filter_transactions: bool = False,
    ) -> tuple[dict[str, tuple[list[tuple[date, float]], list[tuple[date, float]]]], list[dict]]:
        """一次遍历取齐两份数据:按基金分组的买卖份额序列(份额计算用)+ 逐笔流水(现金流用)。

        两者口径不同,但查的是同一批流水,必须同一次取回后分开归属,否则同一批数据要查两遍:
        - 份额序列只收「有基金记录且落在 snapshot_position_ids 内」的持仓——区间生成只算 active 持仓,
          基金记录缺失的持仓不参与计算,否则快照里会多出取不到净值的历史行;
        - 流水默认不过滤持仓(已删持仓真实发生过的净投入不能让区间查询断崖),filter_transactions
          为 True 时只保留有基金记录的持仓(全量重建口径)。
        """
        pairs_by_fund: dict[str, tuple[list[tuple[date, float]], list[tuple[date, float]]]] = {}
        transactions: list[dict] = []
        for pos in positions:
            # 待确认交易不算:买入的份额未定、赎回的到账金额未知,计入会把份额与现金流算歪
            purchases = filter_effective_records(await PurchaseRecordDao.get_purchase_records(query_db, pos.position_id))
            redemptions = filter_effective_records(
                await RedemptionRecordDao.get_redemption_records(query_db, pos.position_id, include_deleted=True)
            )
            in_scope = pos.fund_code in fund_codes
            counts_for_snapshot = in_scope and (
                snapshot_position_ids is None or pos.position_id in snapshot_position_ids
            )
            if counts_for_snapshot:
                entries = pairs_by_fund.setdefault(pos.fund_code, ([], []))
                entries[0].extend((p.purchase_date, float(p.shares)) for p in purchases)
                entries[1].extend((r.redemption_date, float(r.shares)) for r in redemptions)
            if counts_for_snapshot or not filter_transactions:
                # 两侧都「金额优先、缺失回退份额价」:金额是实际收付(买入含申购费、赎回已扣赎回费),
                # 现金分红行靠它才能以负金额扣减净投入(份额为 0,推算永远得 0)
                transactions.extend({
                    'date': p.purchase_date,
                    'type': 'buy',
                    'amount': purchase_amount(p),
                } for p in purchases)
                transactions.extend({
                    'date': r.redemption_date,
                    'type': 'sell',
                    'amount': redemption_amount(r),
                } for r in redemptions)
        return pairs_by_fund, transactions

    @classmethod
    def _build_snapshot_rows(
        cls,
        user_id: int,
        pairs_by_fund: dict[str, tuple[list[tuple[date, float]], list[tuple[date, float]]]],
        nav_cache: dict[str, list[dict]],
        start_date: date,
        end_date: date,
        money_curves: dict[str, 'MoneyAccumCurve'] | None = None,
    ) -> list[dict]:
        """逐日生成快照行(纯内存)。

        份额取市值族(赎回次日起才扣除),与 TWR/MWR 里「赎回是期末事件」的现金流调整假设一致;
        净值取不晚于当日的最近一根,取不到或为 0(坏点)就跳过该基金当日,否则当日市值会被算成 0。
        货币基金(在 money_curves 内):净值恒 1.0、市值按每笔交易从成交日起复利折算
        (每日收益结转语义),份额列保持真实份额——快照表里 nav 与 market_value 不再
        满足「mv = shares × nav」,消费方必须直接用 market_value 列(现有消费方均如此)。
        """
        rows = []
        current = start_date
        while current <= end_date:
            for fund_code, (purchases, redemptions) in pairs_by_fund.items():
                shares = shares_held_on_pairs(purchases, redemptions, current)
                if shares <= 0:
                    continue
                curve = (money_curves or {}).get(fund_code)
                if curve is not None:
                    market_value = money_market_value_on(purchases, redemptions, curve, current)
                    if market_value <= 0:
                        continue
                    rows.append({
                        'user_id': user_id,
                        'snapshot_date': current,
                        'fund_code': fund_code,
                        'shares': shares,
                        'nav': 1.0,
                        'market_value': market_value,
                    })
                    continue
                nav = nav_at_or_before(nav_cache.get(fund_code, []), current)
                if nav is None or nav == 0:
                    continue
                rows.append({
                    'user_id': user_id,
                    'snapshot_date': current,
                    'fund_code': fund_code,
                    'shares': shares,
                    'nav': nav,
                    'market_value': shares * nav,
                })
            current += timedelta(days=1)
        return rows

    @classmethod
    def _build_cash_flow_rows(
        cls, user_id: int, transactions: list[dict], start_date: date, end_date: date
    ) -> list[dict]:
        """逐日现金流水(纯内存)。

        两个字段的符号方向相反,不能混用同一个累加值:
        - `cash_flow` 是资金流向:买入为负(钱出去)、赎回为正;
        - `cumulative_invested` 是累计净投入:买入为正(投入增加)、赎回为负。
        区间开始前的历史交易必须先计入累计净投入,否则区间查询会出现累计投入断崖。

        **赎回记次日**(2026-10-14 修正):份额口径「赎回次日起才扣除」——市值在
        redemption_date+1 才减少,cum_invested 若在赎回当日扣减,赎回日盈亏虚低、
        次日盈亏差虚高(实证:000389 之外 008163 两笔赎回使 10-13 盈亏虚低 53.68、
        10-14 盈亏差放大到 71.41,被用户当成单日暴跌)。赎回的 invested_delta 统一
        移到 date+1,与市值移出同日,快照盈亏的日间变化 = 当日真实盈亏。
        买入份额自成交日起算(市值当日增加),现金流同日,无需移动。
        date+1 落在区间外(end_date 之后)时不计入:市值同样在区间外才减少,口径一致。
        """
        net_invested = 0.0
        daily_invested: dict[date, float] = defaultdict(float)
        for transaction in transactions:
            invested_delta = transaction['amount'] if transaction['type'] == 'buy' else -transaction['amount']
            effective_date = (
                transaction['date'] + timedelta(days=1)
                if transaction['type'] != 'buy'
                else transaction['date']
            )
            if effective_date < start_date:
                net_invested += invested_delta
            elif effective_date <= end_date:
                daily_invested[effective_date] += invested_delta

        rows = []
        current = start_date
        while current <= end_date:
            invested_delta = daily_invested.get(current, 0.0)
            net_invested += invested_delta
            rows.append({
                'user_id': user_id,
                'flow_date': current,
                # 取反后要为 0 时显式写 0.0:负零落库后前端会显示成「-0」
                'cash_flow': -invested_delta if invested_delta else 0.0,
                'cumulative_invested': net_invested,
            })
            current += timedelta(days=1)
        return rows

    @classmethod
    async def _generate_range(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, start_date: date, end_date: date
    ) -> dict:
        """生成区间内每日快照与现金流:取数与计算一次做齐,写入只提交一次。

        快照只处理 active 持仓;现金流按全部持仓(含已删)取,历史净投入要连续。
        """
        active_positions = await PositionDao.get_positions(query_db, user_id)
        all_positions = await PositionDao.get_all_positions(query_db, user_id)
        funds = await cls._get_funds_by_positions(query_db, active_positions)
        nav_cache = await cls._prefetch_nav_records(query_db, redis, {f.code for f in funds.values()})
        money_curves = cls._build_money_curves(funds, nav_cache)
        pairs_by_fund, transactions = await cls._collect_position_data(
            query_db,
            all_positions,
            set(funds),
            snapshot_position_ids={pos.position_id for pos in active_positions},
        )

        snapshots = cls._build_snapshot_rows(
            user_id, pairs_by_fund, nav_cache, start_date, end_date, money_curves
        )
        cash_flows = cls._build_cash_flow_rows(user_id, transactions, start_date, end_date)

        if not await cls._try_lock_user_writes(query_db, user_id):
            logger.warning(f'[快照] 已有写入在进行,放弃本次区间生成 user_id={user_id}')
            raise ServiceWarning(message='已有重建正在进行，请稍后再试')

        await DailySnapshotDao.upsert_snapshots_batch_dao(query_db, user_id, snapshots)
        await DailyCashFlowDao.upsert_cash_flows_batch_dao(query_db, user_id, cash_flows)
        await query_db.commit()

        by_date: dict[date, dict] = defaultdict(lambda: {'total_value': 0.0, 'fund_count': 0})
        for row in snapshots:
            bucket = by_date[row['snapshot_date']]
            bucket['total_value'] += row['market_value']
            bucket['fund_count'] += 1

        details = []
        current = start_date
        while current <= end_date:
            bucket = by_date[current]
            details.append({
                'date': current.isoformat(),
                'total_value': bucket['total_value'],
                'fund_count': bucket['fund_count'],
            })
            current += timedelta(days=1)

        # 手工 dict 键直接写驼峰(与 rebuild 返回契约一致,2026-10-12 实证 snake_case 致前端 undefined)
        return {'daysGenerated': len(details), 'cashFlowDays': len(cash_flows), 'details': details}

    @classmethod
    async def _refresh_range_services(
        cls,
        query_db: AsyncSession,
        redis: aioredis.Redis,
        user_id: int,
        start_date: date,
        end_date: date,
        *,
        nav_cache: dict[str, list[dict]] | None = None,
    ) -> dict:
        """区间增量补数(读路径懒补专用):把「全量重建」的计算与写入限制在 [start_date, end_date]。

        口径必须与 `_rebuild_from_transactions` **完全同一套**(取全部持仓、filter_transactions=True、
        同一份 `_build_snapshot_rows` / `_build_cash_flow_rows`),只把日期切成尾部——这样区间结果与
        全量重建逐行一致,不会出现"某只基金只在最后几天冒出来"的断层。

        踩过的坑:别拿 `_generate_range` 的口径来补尾部。它按"只算 active 持仓"取数,而全量重建是
        "同名的全部持仓(含已删)合并求和";同一只基金在两种口径下份额可能一个 >0 一个 =0
        (实测 `015861`:已删持仓只有一笔 9.61 赎回、无买入,一减就把在用持仓的 9.61 抵消成 0),
        混用会让尾部与历史断层。

        与全量重建的差异只有写入方式:清空换成「区间 upsert + 定向清理份额归零的残留行」,
        其余(写前抢事务级互斥锁、单次 commit)保持一致。
        """
        all_positions = await PositionDao.get_all_positions(query_db, user_id)
        funds = await cls._get_funds_by_positions(query_db, all_positions)
        if nav_cache is None:
            nav_cache = await cls._prefetch_nav_records(query_db, redis, set(funds))
        pairs_by_fund, transactions = await cls._collect_position_data(
            query_db, all_positions, set(funds), filter_transactions=True
        )
        money_curves = cls._build_money_curves(funds, nav_cache)

        snapshots = cls._build_snapshot_rows(
            user_id, pairs_by_fund, nav_cache, start_date, end_date, money_curves
        )
        cash_flows = cls._build_cash_flow_rows(user_id, transactions, start_date, end_date)
        keep_pairs = {(row['snapshot_date'], row['fund_code']) for row in snapshots}
        prune_pairs = plan_prune_pairs(pairs_by_fund, keep_pairs, start_date, end_date)

        if not await cls._try_lock_user_writes(query_db, user_id):
            logger.warning(f'[快照] 已有写入在进行,放弃本次增量补数 user_id={user_id}')
            raise ServiceWarning(message='已有重建正在进行，请稍后再试')

        await DailySnapshotDao.upsert_snapshots_batch_dao(query_db, user_id, snapshots)
        await DailyCashFlowDao.upsert_cash_flows_batch_dao(query_db, user_id, cash_flows)
        pruned = await DailySnapshotDao.delete_snapshot_pairs_dao(query_db, user_id, prune_pairs)
        await query_db.commit()

        logger.info(
            f'[快照] 区间增量补数完成 user_id={user_id} 区间={start_date.isoformat()}~{end_date.isoformat()} '
            f'快照={len(snapshots)} 现金流={len(cash_flows)} 清理残留={pruned}'
        )
        return {'snapshots_upserted': len(snapshots), 'cash_flows_upserted': len(cash_flows), 'pruned': pruned}

    @classmethod
    async def generate_and_save_snapshot_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, target_date: date
    ) -> dict:
        """生成并保存单日快照(只处理 active 持仓)。

        单日只是区间生成的退化情形,共用同一条链路;该入口顺带刷新当日现金流,按日补数时口径才完整。
        """
        result = await cls._generate_range(query_db, redis, user_id, target_date, target_date)
        return result['details'][0]

    @classmethod
    async def generate_and_save_range_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, start_date: date, end_date: date
    ) -> dict:
        """生成日期区间的每日快照与现金流。"""
        result = await cls._generate_range(query_db, redis, user_id, start_date, end_date)
        return {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            **result,
        }

    @classmethod
    async def update_snapshots_for_transaction_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, transaction_date: date
    ) -> None:
        """交易后回填快照:从最新已有快照次日回填到交易当日(已有快照不重复生成)。

        快照失败不影响交易主流程,只记日志。
        """
        try:
            all_positions = await PositionDao.get_all_positions(query_db, user_id)
            if not all_positions:
                return

            latest_snapshot_date = await DailySnapshotDao.get_latest_snapshot_date(query_db, user_id)
            if latest_snapshot_date:
                if latest_snapshot_date >= transaction_date:
                    start_date = transaction_date
                else:
                    start_date = latest_snapshot_date + timedelta(days=1)
            else:
                # 首笔交易前一日也生成,保证现金流基线正确
                start_date = transaction_date - timedelta(days=1)
            # 回溯交易(交易日早于今天)会改变其后**每一天**的份额与市值——
            # 只回填到交易日会留下 [交易日+1, 今天] 的尾部缺口,市值曲线在缺口边界
            # 跳水(2026-10-08 实证:回溯买入后曲线大暴跌,用户手动重建才恢复)。
            # end 一律推到今天,让「交易后回填」与全量重建的口径在覆盖范围上对齐。
            end_date = max(transaction_date, date.today())
            if start_date > end_date:
                return

            funds = await cls._get_funds_by_positions(query_db, all_positions)
            nav_cache = await cls._prefetch_nav_records(query_db, redis, {f.code for f in funds.values()})
            money_curves = cls._build_money_curves(funds, nav_cache)
            pairs_by_fund, transactions = await cls._collect_position_data(query_db, all_positions, set(funds))

            snapshots = cls._build_snapshot_rows(
                user_id, pairs_by_fund, nav_cache, start_date, end_date, money_curves
            )
            cash_flows = cls._build_cash_flow_rows(user_id, transactions, start_date, end_date)

            # 抢不到锁就本次跳过(交易主流程优先):下次交易或读路径还会再补
            if not await cls._try_lock_user_writes(query_db, user_id):
                logger.warning(f'[快照] 已有写入在进行,跳过交易后回填 user_id={user_id}')
                return

            await DailySnapshotDao.upsert_snapshots_batch_dao(query_db, user_id, snapshots)
            await DailyCashFlowDao.upsert_cash_flows_batch_dao(query_db, user_id, cash_flows)
            await query_db.commit()
        except Exception as e:
            await query_db.rollback()
            logger.warning(f'[快照] 交易后回填失败(不影响交易主流程) user_id={user_id} | {e}')

    @classmethod
    async def rebuild_from_transactions_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, *, cooldown_held: bool = False
    ) -> dict:
        """从交易表全量重建快照与现金流——所有**全量**重建入口(手动按钮/交易确认后/导入确认后)的汇聚点。

        读路径懒补已不再走这里:净值新鲜度失效只影响「最新快照日~今天」,改走 `_refresh_range_services`
        增量补尾部(见 `ensure_fresh_services`);本方法保留给「补一笔很久以前的交易/导入」这类
        会改变其后所有日期份额与累计投入的场景。

        两道闸:① Redis 冷却键:单次重建 4~100 秒,**抢不到时先探写锁**——写锁也空闲说明只是
        上一次留下的冷却窗口(此时放行,否则用户点「重建快照」要白等十分钟),写锁被占才算
        "确有重建在执行"、回绝;② DB 事务级写入锁(见 `_try_lock_user_writes`):并发下只有一个
        真正落库,其余快速失败——防重复算的职责收敛到它身上。
        `cooldown_held`:调用方若已持有冷却键则传 True 跳过第一道闸(读路径改走增量后,暂无生产调用方)。
        """
        owns_cooldown = False
        if not cooldown_held:
            if await cls._acquire_rebuild_lock(redis, user_id):
                owns_cooldown = True
            elif await cls._try_lock_user_writes(query_db, user_id):
                # 冷却键被占**但写锁空闲**:说明并没有重建在执行,只是上一次留下的冷却窗口
                # (TTL 600s 远长于单次重建的 4~100s)。此时放行——否则用户点「重建快照」要白等
                # 十分钟,而防重复算的职责本来就该由写锁承担。**不接管**别人的冷却键:
                # owns_cooldown 保持 False,失败时也不去删它。
                locked_at = await redis.get(f'{SNAPSHOT_REBUILD_LOCK_KEY}:{user_id}')
                logger.info(
                    f'[快照] 冷却窗口内但无进行中的重建,放行 user_id={user_id} 上次加锁于={locked_at}'
                )
            else:
                logger.warning(f'[快照] 已有重建正在执行,拒绝重复重建 user_id={user_id}')
                raise ServiceWarning(message='已有重建正在进行（正在执行中），请稍后重试')
        try:
            return await cls._rebuild_from_transactions(query_db, redis, user_id)
        except Exception:
            # 本次抢到的冷却键要还回去,否则失败后用户要白等一个冷却窗口才可能重试
            if owns_cooldown:
                await cls._release_rebuild_lock(redis, user_id)
            raise

    @classmethod
    async def _rebuild_from_transactions(cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int) -> dict:
        """全量重建主体:取数与计算——含净值预取(回源路径内部会 commit 净值行)——全部排在清空之前,
        计算阶段失败则数据分文未动,写入阶段失败则整个事务回滚。冷却键与异常处理由调用方负责。
        """
        all_positions = await PositionDao.get_all_positions(query_db, user_id)
        funds = await cls._get_funds_by_positions(query_db, all_positions)
        fund_codes = set(funds)
        pairs_by_fund, transactions = await cls._collect_position_data(
            query_db, all_positions, fund_codes, filter_transactions=True
        )
        purchase_dates = [transaction['date'] for transaction in transactions if transaction['type'] == 'buy']

        if not purchase_dates:
            if not await cls._try_lock_user_writes(query_db, user_id):
                logger.warning(f'[快照] 已有写入在进行,放弃本次全量重建 user_id={user_id}')
                raise ServiceWarning(message='已有重建正在进行，请稍后再试')
            cleared = await cls.clear_snapshots_and_cash_flows(query_db, user_id)
            await query_db.commit()
            return cls._rebuild_payload(user_id, cleared, 0, 0, {'start': None, 'end': None})

        first_date = min(purchase_dates)
        today = date.today()
        nav_cache = await cls._prefetch_nav_records(query_db, redis, fund_codes)
        money_curves = cls._build_money_curves(funds, nav_cache)
        snapshots = cls._build_snapshot_rows(
            user_id, pairs_by_fund, nav_cache, first_date, today, money_curves
        )
        cash_flows = cls._build_cash_flow_rows(user_id, transactions, first_date, today)

        # 计算阶段内部 commit 过(净值回源),事务级锁只能抢在这里——写入之前、且不能再有 commit
        if not await cls._try_lock_user_writes(query_db, user_id):
            logger.warning(f'[快照] 已有写入在进行,放弃本次全量重建 user_id={user_id}')
            raise ServiceWarning(message='已有重建正在进行，请稍后再试')

        cleared = await cls.clear_snapshots_and_cash_flows(query_db, user_id)
        await DailySnapshotDao.insert_snapshots_bulk_dao(query_db, snapshots)
        await DailyCashFlowDao.insert_cash_flows_bulk_dao(query_db, cash_flows)
        await query_db.commit()

        logger.info(
            f'[快照] 全量重建完成 user_id={user_id} 快照={len(snapshots)} 现金流={len(cash_flows)} '
            f'区间={first_date.isoformat()}~{today.isoformat()}'
        )
        return cls._rebuild_payload(
            user_id,
            cleared,
            len(snapshots),
            len(cash_flows),
            {'start': first_date.isoformat(), 'end': today.isoformat()},
        )

    @classmethod
    def _rebuild_payload(
        cls,
        user_id: int,
        cleared: dict,
        snapshots_created: int,
        cash_flows_created: int,
        date_range: dict,
    ) -> dict:
        """重建回执(驼峰直出给前端):回执形状只在这里定义一次,两个 return 都走它。

        嵌套层不交给 CamelCaseUtil——它是浅转换(只转顶层键),`rebuilt.date_range` 会整层漏过去;
        而前端 `SnapshotRebuildResult` 按驼峰读 `rebuilt.dateRange.start`,漏一个键就会在拼 toast
        字符串时抛异常,把它后面的 `invalidateQueries`(列表重取)一起带走——表现为"重建成功但
        页面既不提示也不刷新"。
        """
        return {
            'userId': user_id,
            'cleared': CamelCaseUtil.transform_result(cleared),
            'rebuilt': {
                'snapshotsCreated': snapshots_created,
                'cashFlowsCreated': cash_flows_created,
                'dateRange': date_range,
            },
        }

# ---- 后台重建(删除交易后用) ----
# HTTP 响应不等重建:全量重建实测 5~98 秒,同步执行会把删除接口拖成几十秒,
# 用户以为没删掉而重复点击,第二次撞上「记录已不存在」产生误导性错误 toast。
REBUILD_BG_RETRY_ATTEMPTS = 3
REBUILD_BG_RETRY_DELAY_SECONDS = 20
REBUILD_BUSY_MARKER = '已有重建正在进行'


async def rebuild_snapshots_in_background(user_id: int, redis: aioredis.Redis) -> None:
    """后台快照全量重建(配合 FastAPI BackgroundTasks)。

    每次尝试用**独立会话**(调用方的会话在响应返回后已关闭);重试语义与导入确认一致——
    只对「重建被占用」做有界重试(占锁者通常正是上一次删除触发的重建),
    其它异常记日志放弃:下次删除交易或手动重建会再收敛,快照短暂滞后可接受。
    """
    from db.database import AsyncSessionLocal  # 局部导入:db 是叶子,避免潜在循环

    for attempt in range(1, REBUILD_BG_RETRY_ATTEMPTS + 1):
        try:
            async with AsyncSessionLocal() as session:
                result = await SnapshotService.rebuild_from_transactions_services(
                    session, redis, user_id
                )
            logger.info(
                f'[快照] 后台重建完成 user_id={user_id} '
                f'快照={result["rebuilt"]["snapshotsCreated"]} '
                f'现金流={result["rebuilt"]["cashFlowsCreated"]} 第={attempt} 次'
            )
            return
        except ServiceWarning as exc:
            if REBUILD_BUSY_MARKER not in str(exc):
                logger.warning(f'[快照] 后台重建失败 user_id={user_id} | {exc}')
                return
            if attempt < REBUILD_BG_RETRY_ATTEMPTS:
                logger.info(
                    f'[快照] 后台重建被占用,{REBUILD_BG_RETRY_DELAY_SECONDS}s 后重试 '
                    f'user_id={user_id} 第={attempt} 次'
                )
                await asyncio.sleep(REBUILD_BG_RETRY_DELAY_SECONDS)
                continue
            logger.warning(f'[快照] 后台重建被占用,重试耗尽 user_id={user_id}(下次删除或手动重建会收敛)')
            return
        except Exception as exc:
            logger.warning(f'[快照] 后台重建异常(不影响删除结果) user_id={user_id} | {exc}')
            return
