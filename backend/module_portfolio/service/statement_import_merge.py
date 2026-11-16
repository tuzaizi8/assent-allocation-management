"""交易导入的「按平台累加」判重(纯函数,无 DB/IO,专供单测)。

语义(2026-09-19 起):同一平台内**库里已有的一律保留**;新文件里与之重复的丢弃,只追加真正
的新记录——库里 2021~2025 + 新文件 2022~2026 → 2022~2025 判重丢弃、只补 2026。不同平台
之间**永不互相判重**(两平台各买一次同一只基金本就是两笔,金额相加后进快照与现金流)。

判重键只用「文件侧稳定、跨导出件可比」的字段:

- 买入 `(日期, 基金代码, 方向, 金额)`:金额一定会落库(`amount` 列);份额可能是「金额÷净值」
  的换算值、待确认时是 0 后又被回填,**会漂移**,不能进键。
- 赎回 `(日期, 基金代码, 方向, 份额)`:赎回落库**不写 amount**,只能靠份额。

订单号不进键:它不入库,而且支付宝的是**组合批次号**(同一订单跨多只基金天然重复,见 99 §十三)。

同一个键可能对应多笔真实交易,故按「**多重集**」配对而不是集合去重:库里 2 条、新文件 2 条 →
全部判重;库里 1 条、新文件 2 条 → 补 1 条。
"""

from module_portfolio.service.statement_validators import DIRECTION_PURCHASE, direction_of

# 容差:吸收不同导出件的分位/手续费口径差,量级对齐 alipay.yaml 的 tolerance.amount_vs_value(0.02)
# 与 statement_import_service.IMPORTED_FULL_REDEMPTION_TOLERANCE(0.5 份)。
#
# 刻意只用绝对容差、不做「按比例放大」:比例容差会把「同一天、同方向、金额相近的两笔真实交易」
# 并成同一笔——那是**丢数据**且不可撤销;而漏判的代价只是重复累加,看得见、可用三级清空重来。
# 同一笔交易在同一平台的两种导出件里取的都是「确认金额/确认份额」,差异本就在分位级。
AMOUNT_ABS_TOLERANCE = 0.02
SHARES_ABS_TOLERANCE = 0.5


def _close(left: float, right: float, abs_tolerance: float) -> bool:
    return abs(left - right) <= abs_tolerance


def _match_value(record: dict, *, is_purchase: bool) -> float:
    """参与判重的数值:买入取金额、赎回取份额。

    买入没有金额时取**份额**:红利再投资就是「金额 0 + 份额 N」的买入行(库内 amount 存成 NULL),
    单价同样是 0。若回退成「份额×单价」,同一天的两笔再投(003547 是 5.86 + 3.91)会一起算成 0 →
    互相混成一笔,重导时分辨不出谁已经导过。
    """
    if not is_purchase:
        return float(record.get('shares') or 0)
    amount = float(record.get('amount') or 0)
    return amount if amount else float(record.get('shares') or 0)


def _bucket_key(record: dict) -> tuple[str, str, bool] | None:
    """判重桶:同一天 + 同一只基金 + 同一方向。判不了(缺日期/基金/方向)返回 None → 视为新记录。"""
    tx_date = str(record.get('date') or '').strip()
    fund_code = str(record.get('fund_code') or '').strip()
    direction = direction_of(record.get('type'))
    if not tx_date or not fund_code or not direction:
        return None
    return (tx_date, fund_code, direction == DIRECTION_PURCHASE)


def plan_import_merge(
    incoming: list[dict],
    existing: list[dict],
    *,
    amount_abs_tolerance: float = AMOUNT_ABS_TOLERANCE,
    shares_abs_tolerance: float = SHARES_ABS_TOLERANCE,
) -> tuple[list[dict], int]:
    """同平台内做多重集判重:已有优先。

    `incoming` = 本次文件里待落库的记录;`existing` = **本平台**已有记录(调用方已按平台圈好范围)。
    两侧都用同一套字段名:`{'date': 'YYYY-MM-DD', 'fund_code': str, 'type': '买入'/'赎回',
    'amount': float, 'shares': float, 'unit_price': float}`。

    返回 `(要新增的记录, 被判重丢弃的条数)`——返回的是 `incoming` 的原对象(调用方还要拿它落库)。
    """
    pools: dict[tuple[str, str, bool], list[float]] = {}
    for row in existing:
        key = _bucket_key(row)
        if key is None:
            continue
        pools.setdefault(key, []).append(_match_value(row, is_purchase=key[2]))

    kept: list[dict] = []
    skipped = 0
    for record in incoming:
        key = _bucket_key(record)
        pool = pools.get(key) if key is not None else None
        if not pool:
            kept.append(record)
            continue
        tolerance = amount_abs_tolerance if key[2] else shares_abs_tolerance
        value = _match_value(record, is_purchase=key[2])
        hit = next((index for index, other in enumerate(pool) if _close(other, value, tolerance)), None)
        if hit is None:
            kept.append(record)
            continue
        # 消费掉这一条(多重集):库里两条相同记录只该压掉新文件里的两条,不能一把压完
        pool.pop(hit)
        skipped += 1
    return kept, skipped
