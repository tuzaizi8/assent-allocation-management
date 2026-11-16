"""持仓计算公共工具:份额@日期、最近净值@日期、日收益。

份额口径有**两族**,不能混用(此前项目里 6 处实现混着写,导致「有快照/无快照」的
市值与 TWR 不一致,也一度让日收益基数漂移):

| 族 | 语义 | 买入 | 赎回 | 使用者 |
|----|------|------|------|--------|
| `shares_held_on` | 该日**仍持有**(赎回次日起才扣除) | `<=` | `<` | 每日市值序列与 TWR/MWR(快照路径 + 实时兜底) |
| `shares_held_at_close` | 该日**收盘后**(赎回当日已扣除) | `<=` | `<=` | 日收益基数、历史持仓值 |

为什么要分两族:
- 市值族服务 TWR/MWR,而 TWR 的现金流调整明确假设「**赎回是期末事件**」——
  赎回日当天的市值仍需包含被赎回份额,资金次日起离开;两处必须同口径。
- 日收益族服务「前一净值日末已持有的份额」语义(赎回当日按当日净值成交、份额已离开),
  该口径由 `tests/test_daily_fund_profit.py` 的两个用例双向锁定。

净值口径:取 **不晚于目标日的最近一根** 单位净值(非交易日自动沿用前一交易日)。
"""

from bisect import bisect_right
from datetime import date, timedelta

# 份额低于该阈值即视为 0(百万分之一份,远低于任何真实持仓的最小单位)。
# 只用于吸收「全额赎回后浮点减法留下的残渣」,例如 0.1 + 0.2 - 0.3 = 5.55e-17。
SHARES_ZERO_EPSILON = 1e-6

# ---- 下单切分:15:00 是基金交易的收盘线 ----
# 15:00 是收盘线:**下单时间**在 15:00 之后的申购/赎回按**下一交易日**净值成交。
# 边界取「严格晚于 15:00」:15:00 整点仍是收盘那一刻的成交,按当日净值。
# 顺延只推一个自然日;若撞上非交易日(周末/节假日),由 `AkshareService.resolve_target_nav`
# 的「顺延到第一条 nav_date ≥ 目标日」兜住(周五 15:01 → 周六 → 实际落到周一)。
ORDER_CUTOFF_HOUR = 15
ORDER_CUTOFF_MINUTES = ORDER_CUTOFF_HOUR * 60


def order_confirm_date(order_date: date | str, order_minutes: int) -> str:
    """下单日 + 下单时刻(当日分钟数)→ 确认日(纯函数,供截图导入使用)。"""
    parsed = date.fromisoformat(_as_date_str(order_date))
    if order_minutes <= ORDER_CUTOFF_MINUTES:
        return parsed.isoformat()
    return (parsed + timedelta(days=1)).isoformat()


def next_confirm_date(order_date: date | str) -> str:
    """确认日顺延一日(纯函数,供手工录入的「15:00 后」开关使用)。"""
    parsed = date.fromisoformat(_as_date_str(order_date))
    return (parsed + timedelta(days=1)).isoformat()


def _as_date_str(target: date | str) -> str:
    """统一成 yyyy-MM-dd 字符串:净值记录里的 nav_date 就是该格式,字符串比较即日期比较。"""
    return target.isoformat() if isinstance(target, date) else str(target)


def nav_at_or_before(nav_records: list[dict] | None, target_date: date | str) -> float | None:
    """取不晚于目标日的最近单位净值(市值计算永远用 unit_nav);目标日早于首根净值返回 None。"""
    record = nav_record_at_or_before(nav_records, target_date)
    return None if record is None else record.get('unit_nav', 0)


def nav_record_at_or_before(nav_records: list[dict] | None, target_date: date | str) -> dict | None:
    """取不晚于目标日的最近一条净值记录(需要同时拿 nav_date 与 unit_nav 时用)。"""
    if not nav_records:
        return None
    target = _as_date_str(target_date)
    applicable = [r for r in nav_records if r.get('nav_date', '') <= target]
    return applicable[-1] if applicable else None


def nav_value_from_map(nav_by_date: dict[str, dict], target_date: date | str) -> float | None:
    """按 {nav_date: 记录} 索引取不晚于目标日的最近单位净值。

    用 max(键) 而非「先滤后排再取末位」:索引字典的插入顺序不构成契约,
    不能假设已按日期升序,否则会取到错误的一根。
    """
    if not nav_by_date:
        return None
    target = _as_date_str(target_date)
    applicable = [k for k in nav_by_date if k <= target]
    if not applicable:
        return None
    return nav_by_date[max(applicable)].get('unit_nav', 0)


def is_snapshot_nav_stale(
    snapshot_date: date | str | None,
    snapshot_navs: dict[str, float],
    nav_cache: dict[str, list[dict]] | None,
    today: date | str | None = None,
) -> bool:
    """最新一日的快照是否已落后于当前可用净值(读路径懒补快照的判定,纯函数无 IO)。

    **不能只比日期**:净值按「不晚于当日的最近一根」取值,两个方向的滞后都会让当日市值失真——
    ① 日期滞后:快照日早于某只基金的最新净值日(如 09-15 凌晨重建时当日净值未发布,09-15 行
       沿用 09-14 的净值,当日收益恒为 0);
    ② 同日不一致:快照日已等于最新净值日,但那一行存的是**后到净值之前**取的旧根(如某基金
       数据源发布滞后,09-12~09-15 四天都写着 09-11 的净值,之后才补上 09-14 的真实净值)。

    因此逐只比对「快照存的 nav」与「按同口径现在应取的 nav」(`nav_at_or_before` 与快照构建
    同一实现,容差 1e-6 吸收落库精度)。判定顺序是先比净值、再比日期:取不到净值序列、或该日
    取不到净值(序列缺失/尚未开始)的基金**跳过**——判不了就不该拿它触发重建,否则重建反而会
    因取不到净值而丢掉那一行。空入参返回 False。

    日期滞后只看**不晚于 today 的最后一根**净值:重建的上界是今天,若净值序列里出现「明天/未来
    日期」的脏记录(数据源异常),拿 `records[-1]` 比会永远滞后 → 每 10 分钟空转重建一次。
    """
    if snapshot_date is None or not snapshot_navs or not nav_cache:
        return False
    target = _as_date_str(snapshot_date)
    horizon = _as_date_str(today) if today is not None else _as_date_str(date.today())
    for fund_code, snapshot_nav in snapshot_navs.items():
        records = nav_cache.get(fund_code)
        if not records:
            continue
        expected_nav = nav_at_or_before(records, target)
        if expected_nav is None:
            continue
        if abs(float(expected_nav) - float(snapshot_nav)) > 1e-6:
            return True
        # 同日净值对得上,但可用净值已延伸到更晚的交易日 → 快照少了一段真实行情
        latest_usable = nav_record_at_or_before(records, horizon)
        if latest_usable and str(latest_usable.get('nav_date') or '') > target:
            return True
    return False


def shares_held_on(purchases: list, redemptions: list, target_date: date | str) -> float:
    """市值族(ORM 记录):目标日仍持有的份额(买入 <= 计入,赎回 < 扣除)。"""
    return shares_held_on_pairs(_to_pairs(purchases, 'purchase_date'), _to_pairs(redemptions, 'redemption_date'), target_date)


def shares_held_at_close(purchases: list, redemptions: list, target_date: date | str) -> float:
    """日收益族(ORM 记录):目标日收盘后持有的份额(买入 <= 计入,赎回 <= 扣除)。"""
    return shares_held_at_close_pairs(
        _to_pairs(purchases, 'purchase_date'), _to_pairs(redemptions, 'redemption_date'), target_date
    )


def shares_held_on_pairs(
    purchases: list[tuple[date | str, float]],
    redemptions: list[tuple[date | str, float]],
    target_date: date | str,
) -> float:
    """市值族((日期, 份额) 序列):口径同 shares_held_on,供已预取成元组的分析路径复用。"""
    return _accumulate(purchases, redemptions, target_date, redemption_inclusive=False)


def shares_held_at_close_pairs(
    purchases: list[tuple[date | str, float]],
    redemptions: list[tuple[date | str, float]],
    target_date: date | str,
) -> float:
    """日收益族((日期, 份额) 序列):口径同 shares_held_at_close。"""
    return _accumulate(purchases, redemptions, target_date, redemption_inclusive=True)


def remaining_shares(purchases: list, redemptions: list) -> float:
    """当前剩余份额 = Σ买入 − Σ赎回(不按日期过滤,用于当前持仓视角)。"""
    return max(
        0.0,
        sum(float(p.shares) for p in purchases) - sum(float(r.shares) for r in redemptions),
    )


def purchase_amount(record) -> float:
    """一笔买入的成本增量:落库金额(实际掏的钱)优先,缺失时回退「份额 × 单价」。

    金额可能是 0(红利再投资落成「金额 0」的买入行)或负(现金分红落成「0 份额 + 负金额」)——
    两种都得按原值参与成本累加,所以不能用 `amount or ...` 回退。
    """
    amount = getattr(record, 'amount', None)
    if amount is not None:
        return float(amount)
    return float(record.shares) * float(record.cost_price)


def redemption_amount(record) -> float:
    """一笔赎回的**实际到账**金额:落库「确认金额」优先,缺失才回退「份额 × 赎回净值」。

    与 `purchase_amount` 对称。确认金额已扣赎回费,是"真正拿回多少钱"的口径;
    `份额 × 净值` 是不扣费的毛额,只在老数据(amount 未落库)时才用它兜底——
    2026-09-22 前导入的赎回行 amount 全为空,没有这个回退会把它们算成 0。
    """
    amount = getattr(record, 'amount', None)
    if amount is not None:
        return float(amount)
    return float(record.shares) * float(record.nav_price)


def cost_basis_walk(
    purchases: list[tuple[date | str, float, float]],
    redemptions: list[tuple[date | str, float, float]],
) -> tuple[float, float, float]:
    """时序加权平均(成本随赎回结转):(剩余份额, 持仓成本, 已实现收益)。

    买入累加成本,卖出按**当时**的加权平均成本结转一部分成本出去,并把「卖出对价 − 结转成本」
    计进已实现收益。这样剩余份额的成本不再被已经卖掉的份额污染——
    2026-09-22 修:旧实现里持仓成本恒等于「全部买入金额」,161725 买的 808.44 份里有 258.44 份
    早已卖出,成本仍挂着 550.01,平均成本被算成 1.0000(实际 0.6696)、浮亏放大到 -257.24。

    入参语义:`purchases` 的第三项是**金额**(这笔实际掏的钱:红利再投资为 0、现金分红为负),
    `redemptions` 的第三项是**赎回净值**(单价)。为什么用金额而不是「份额 × 单价」——
    红利再投/现金分红这两种「份额与金额不同步」的行只有金额表达得了,顺带让待确认买入
    (净值未发布、份额记 0 但钱已扣)也算得对。

    两条约定:
    - 同日**先买后卖**(排序键把买入排在前面):当日买入参与当日卖出的成本结转;
    - 卖出份额超过持有份额时(导出件截断导致的数据缺口,如某行买 111.55 / 卖 113.60),
      超出部分按**该行整体买入均价**结转,行末可能出现负的剩余份额/成本——调用方按该行是否
      还有持仓决定是否展示,不要据此报错。

    入参照 `shares_held_on_pairs`:已预取成元组,便于单测直接钉数。
    """
    events = [(_as_date_str(day), 0, float(shares), float(value)) for day, shares, value in purchases]
    events += [(_as_date_str(day), 1, float(shares), float(nav)) for day, shares, nav in redemptions]
    events.sort(key=lambda event: (event[0], event[1]))

    bought_shares = sum(event[2] for event in events if event[1] == 0)
    bought_cost = sum(event[3] for event in events if event[1] == 0)
    fallback_unit = bought_cost / bought_shares if bought_shares > SHARES_ZERO_EPSILON else 0.0

    shares = cost = realized = 0.0
    for _, kind, qty, value in events:
        if kind == 0:
            # 0 份额的买入行照样得算成本:现金分红就是「0 份额 + 负金额」,它只冲减成本
            shares += qty
            cost += value
            continue
        if qty <= 0:
            continue
        unit = cost / shares if shares > SHARES_ZERO_EPSILON else fallback_unit
        cost_of_sold = unit * qty
        realized += qty * value - cost_of_sold
        cost -= cost_of_sold
        shares -= qty
    return shares, cost, realized


def fund_realized_profit(purchases: list, redemptions: list, *, redeem_price_of=None) -> float:
    """**全基金**已实现收益(ORM 记录):该基金全部持仓行历次卖出结转的盈亏合计。

    使用者要的是「这只基金所有交易一共赚亏多少」——同一只基金常有「买入→清仓→再买入」的多轮,
    只看当前行就把以前各轮已落袋的盈亏丢了(162725 实测:四轮合计 -34.98)。

    **按持仓行分组各走一次结转,行与行不共用成本链**:已清仓行若走过「卖出多于买入」的数据缺口
    (导出件截断导致,某些行买 111.55 / 卖 113.60),合成一条链会把它的负成本带进后一行的均价、
    把后一行的成本算歪(实测差 13.87 元)。这里只把各轮已实现合计起来。

    `redeem_price_of`:可选的赎回单价回调(默认 `r.nav_price`)。货币基金必须传
    「amount/shares」——其 nav 恒 1.0 而真实到账含每日结转收益,名义单价会把
    已实现盈亏整个吞成 0(2026-10-08 用户发现);普通基金不传,行为不变。
    """
    price_of = redeem_price_of or (lambda r: float(r.nav_price))
    row_ids = {p.position_id for p in purchases} | {r.position_id for r in redemptions}
    total = 0.0
    for row_id in row_ids:
        _, _, realized = cost_basis_walk(
            [(p.purchase_date, p.shares, purchase_amount(p)) for p in purchases if p.position_id == row_id],
            [(r.redemption_date, r.shares, price_of(r)) for r in redemptions if r.position_id == row_id],
        )
        total += realized
    return total


def daily_profit(shares: float, nav: float, prev_nav: float) -> float:
    """日收益 = 档位前一净值日末已持有份额 × (档位净值 − 前一净值日净值)。

    全项目统一 round 到 4 位:此前持仓列表不 round、日收益端点 round(,4),
    同一语义两种精度,前端消费时对不上。
    """
    return round(shares * (nav - prev_nav), 4)


def is_effective_record(status: str | None) -> bool:
    """交易记录是否已生效。

    待确认(status='0')表示所选日期的净值尚未发布:买入只记了金额、赎回只有份额而没有
    净值。这类记录若参与计算会污染收益率——赎回收不到对价(份额已扣、钱没记回来)会被
    当成亏损;故份额与现金流都只认已生效记录。
    """
    return status != '0'


def filter_effective_records(records: list) -> list:
    """剔除待确认交易(见 is_effective_record):份额序列与逐笔流水共用同一份过滤。"""
    return [record for record in records if is_effective_record(getattr(record, 'status', '1'))]


def _to_pairs(records: list, date_attr: str) -> list[tuple[date, float]]:
    """ORM 记录 → (日期, 份额) 序列:统一到纯数据形态后只保留一份累加实现。"""
    return [(getattr(r, date_attr), float(r.shares)) for r in records]


def _accumulate(
    purchases: list[tuple[date | str, float]],
    redemptions: list[tuple[date | str, float]],
    target_date: date | str,
    *,
    redemption_inclusive: bool,
) -> float:
    """份额累加的唯一实现:买入恒按 <= 计入,赎回按族决定 < 还是 <= 扣除。

    结果低于 `SHARES_ZERO_EPSILON` 一律归 0:全额赎回后 `Σ买入 − Σ赎回` 的浮点减法会留下
    1e-16 量级残渣(2026-09-20 实测 6 只已清仓基金在快照里仍每天出一行、份额 8.9e-16~1.4e-14,
    四舍五入到分都是 0.00,却让快照列表的「基金数」比在用持仓多 6)。归零同时让
    `plan_prune_pairs` 的「份额归零就删尾部行」生效——否则那些幽灵行连重建都清不掉。
    """
    target = _as_date_str(target_date)
    bought = sum(shares for day, shares in purchases if _as_date_str(day) <= target)
    if redemption_inclusive:
        sold = sum(shares for day, shares in redemptions if _as_date_str(day) <= target)
    else:
        sold = sum(shares for day, shares in redemptions if _as_date_str(day) < target)
    remaining = bought - sold
    if remaining < SHARES_ZERO_EPSILON:  # 含负值(超卖)与浮点残渣
        return 0.0
    return remaining


class MoneyAccumCurve:
    """货币基金累计收益曲线(日期升序),供「每日收益结转」市值的复利折算。

    由 AkshareService.get_money_fund_nav_series 的合成净值序列构造
    (accum_nav = 万份收益逐日连乘,基金成立日起算)。
    """

    def __init__(self, series: list[dict]) -> None:
        self._dates: list[str] = [r['nav_date'] for r in series]
        self._accums: list[float] = [float(r['accum_nav']) for r in series]

    def accum_at(self, on_date: date) -> float:
        """取不晚于 on_date 的最近累计系数。

        回退次序:≤ 当日的最近一根 → 最早一根(日期早于基金首日的防御兜底;
        份额从买入日起算,买入日必在序列内)。空曲线返回 1.0——无收益数据时
        市值退化为份额本金,优于 0。
        """
        if not self._dates:
            return 1.0
        idx = bisect_right(self._dates, on_date.isoformat())
        if idx == 0:
            return self._accums[0]
        return self._accums[idx - 1]

    def last_two_dates(self) -> tuple[str, str]:
        """(最新净值日, 前一净值日);不足两根时第二位为空串。"""
        if not self._dates:
            return '', ''
        if len(self._dates) == 1:
            return self._dates[0], ''
        return self._dates[-1], self._dates[-2]

    def nth_dates(self, offset: int) -> tuple[str, str]:
        """(倒数第 offset+1 根, 倒数第 offset+2 根);不足两根返回 ('', '')。

        offset 语义与日收益端点一致:0 为最新档(今日档)、1 为前一档(昨日档)。
        """
        idx = len(self._dates) - 1 - offset
        if idx < 1:
            return '', ''
        return self._dates[idx], self._dates[idx - 1]


def money_market_value_on(
    purchases: list[tuple[date, float]],
    redemptions: list[tuple[date, float]],
    curve: MoneyAccumCurve,
    on_date: date,
) -> float:
    """货币基金市值(每日收益结转语义,纯函数)。

    按日结转的货基收益逐日转为新增份额,等价于**每笔交易从自身成交日起按
    累计收益曲线复利增值**。赎回按 nav=1 移出份额,其未来增值一并移出;
    **赎回按 FIFO 从最早的未耗尽买入移出,被移出份额继承该买入的锚点日**
    ——2026-10-08 修正:此前赎回按赎回日 accum 移出、买入按买入日 accum
    挂账,跨轮申赎(清仓后再买)时赎回移出价 ≠ 在场买入锚点,每轮清仓留下
    「份额×(accum(赎)−accum(买))/accum(买)」的永久正残差(实证:000389
    五轮申赎累计幻影收益 50 元,模型总收益 56.7 vs 用户真实 6 元)。

    **交易必须限定在 on_date 之后才计入**(`day <= on_date`):否则回溯录入的
    交易会在其成交日之前就贡献「幻影市值」——2026-10-08 实证:2021-12-09 的
    买入在 2021-11-16 的快照里提前出现 349.5,被 TWR 当成收益,收益率曲线
    在两笔买入日各制造一次暴涨/暴跌。这与普通基金的 shares_held_on_pairs
    「份额从成交日起算」口径必须严格对齐。

    **赎回当天仍持有**(与市值族口径一致,`d_j < on_date` 才扣除):赎回当日
    的快照必须包含被赎回份额的市值,次日才消失——否则赎回日市值骤降为残余
    收益(实证 2026-10-08:700 份全赎当日 mv=1.147,单日 −99.8%)。
    """
    base = curve.accum_at(on_date)
    if base <= 0:
        return 0.0
    # FIFO 配对:锚点按日期升序,赎回按时间序逐笔消耗最早未耗尽的买入
    anchors: list[list] = [
        [day, shares] for day, shares in sorted(purchases) if day <= on_date
    ]
    li = 0
    for redemption_day, redemption_shares in sorted(redemptions):
        if redemption_day >= on_date:
            break
        need = redemption_shares
        while need > 1e-9 and li < len(anchors):
            if anchors[li][1] <= 1e-9:
                li += 1
                continue
            take = min(anchors[li][1], need)
            anchors[li][1] -= take
            need -= take
        # need 仍有剩余(超赎脏数据)时忽略,不产生负锚
    return sum(
        remain * base / curve.accum_at(day)
        for day, remain in anchors
        if remain > 1e-9
    )
