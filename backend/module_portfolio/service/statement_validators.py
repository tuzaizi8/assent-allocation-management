"""交易记录的守恒校验(纯函数,分级:error 拦截落库 / warning 放行告警)。

只做「能自证对错」的检查:基金代码位数、日期可解析、份额非负、金额 ≈ 份额 × 净值、
订单号不重复、买卖方向可判定。金额与净值的口径差异(手续费、四舍五入)只告警,
净值为 0 时按「金额 ÷ 份额」兜底——这些都不该拦住一次导入。
方向不是从类型列认出来的(适配器标了 `_direction_from_shares`)、只能靠申请份额推断的行:
照样放行,但产出一条告警请使用者核对(「定投卖出」被误判成买入就是这类行没被看见)。

校验会被调用两次:preview 时(告警给用户看)与 confirm 落库前(硬拦截最后一道)。
"""

import re
from dataclasses import dataclass
from datetime import date

# 金额与「份额 × 净值」的相对容差(适配器可用 tolerance.amount_vs_value 覆盖)
AMOUNT_TOLERANCE_RATIO = 0.005
# 绝对容差下限:几分钱的四舍五入不报
AMOUNT_TOLERANCE_MIN = 0.02
# 低于该偏差视为纯四舍五入,连告警都不发
AMOUNT_NOISE = 0.005

# 「转换入/转入」与下面的「转换出/转出」对称:转换的两条腿按动词定方向,不再掉进申请列兜底
BUY_WORDS = ('买', '申购', '认购', '定投', '转换入', '转入')
# 与 statement_adapters.SELL_WORDS 必须逐字相同(有单测钉住),否则两处口径会漂
SELL_WORDS = ('卖', '赎回', '转换出', '转出')

DIRECTION_PURCHASE = 'purchase'
DIRECTION_REDEMPTION = 'redemption'


@dataclass(frozen=True)
class Issue:
    """一条校验问题(level=error 拦截,level=warning 放行)。"""

    level: str
    field: str
    message: str
    row: int | None = None
    page: int | None = None


def direction_of(value: str) -> str:
    """把各种写法的买卖方向归一成 purchase / redemption / ''(判不出)。

    **卖出词优先**,与适配器 `_resolve_type` 同一口径:「定投卖出」同时含买入词(定投)与
    卖出词(卖),方向由动词决定(买入词只是限定语);反过来的「卖出买入」不存在。
    """
    text = str(value or '').strip()
    if text in (DIRECTION_PURCHASE, DIRECTION_REDEMPTION):
        return text
    if any(word in text for word in SELL_WORDS):
        return DIRECTION_REDEMPTION
    if any(word in text for word in BUY_WORDS):
        return DIRECTION_PURCHASE
    return ''


def _issue(level: str, record: dict, field: str, message: str) -> Issue:
    return Issue(
        level=level,
        field=field,
        message=message,
        row=record.get('row'),
        page=record.get('page'),
    )


def validate_records(
    records: list[dict], tolerance: dict[str, float] | None = None, today: date | None = None
) -> tuple[list[dict], list[Issue], list[Issue]]:
    """校验并分级。

    返回 (可落库记录, 拦截级问题, 告警级问题);会就地补全净值为 0 的记录(金额 ÷ 份额)。
    """
    ratio = float((tolerance or {}).get('amount_vs_value', AMOUNT_TOLERANCE_RATIO))
    current_day = today or date.today()
    kept: list[dict] = []
    errors: list[Issue] = []
    warnings: list[Issue] = []
    seen_orders: dict[tuple[str, str, str], int | None] = {}

    for record in records:
        row_errors: list[Issue] = []
        row_warnings: list[Issue] = []

        # 账本表达不了的类型(红利再投资 / 分红):直接跳过并说清楚原因——不要冒「买卖方向无法判定」
        unsupported = record.get('unsupported')
        if unsupported:
            message = f'该行（{unsupported}）暂不支持导入，已跳过（请手工处理）'
            errors.append(_issue('error', record, 'type', message))
            continue

        fund_code = str(record.get('fund_code') or '')
        if not re.fullmatch(r'\d{6}', fund_code):
            note = f'（{record["resolve_note"]}）' if record.get('resolve_note') else ''
            row_errors.append(
                _issue('error', record, 'fundCode', f'基金代码「{fund_code or "空"}」不是 6 位数字{note}')
            )

        date_text = record.get('date')
        if not date_text:
            row_errors.append(_issue('error', record, 'date', '交易日期无法解析'))
        else:
            try:
                parsed = date.fromisoformat(str(date_text))
                if parsed > current_day:
                    row_warnings.append(_issue('warning', record, 'date', f'交易日期 {date_text} 在未来，请确认'))
            except ValueError:
                row_errors.append(_issue('error', record, 'date', f'交易日期「{date_text}」无法解析'))

        direction = direction_of(record.get('type') or '')
        if not direction:
            value = record.get('type') or ''
            row_errors.append(
                _issue('error', record, 'type', f'买卖方向无法判定（交易类型为「{value or "空"}」且无申请份额列）')
            )
        elif record.get('_direction_from_shares'):
            # 类型列认不出、方向只能靠「申请份额空不空」推断:放行,但让使用者在预览页看见
            guess = '买入' if direction == DIRECTION_PURCHASE else '赎回'
            row_warnings.append(
                _issue('warning', record, 'type', f'交易类型未能识别，已按申请份额推断为「{guess}」，请核对')
            )

        shares = float(record.get('shares') or 0)
        amount = float(record.get('amount') or 0)
        unit_price = float(record.get('unit_price') or 0)

        if shares < 0:
            row_errors.append(_issue('error', record, 'shares', f'份额为负（{shares}）'))
        if direction == DIRECTION_REDEMPTION and shares <= 0:
            row_errors.append(_issue('error', record, 'shares', '赎回份额缺失，无法计算'))
        if record.get('nav_pending'):  # 列表式截图:该交易日净值未发布,只能按待确认落库(只记金额)
            row_warnings.append(_issue('warning', record, 'shares', '该交易日净值尚未发布，份额待确认（先按金额落库）'))

        if shares > 0 and unit_price <= 0 and amount > 0:
            unit_price = round(amount / shares, 6)
            record['unit_price'] = unit_price
            row_warnings.append(_issue('warning', record, 'unitPrice', '净值为 0，已按「金额 ÷ 份额」兜底'))

        if shares > 0 and unit_price > 0 and amount > 0:
            deviation = abs(amount - shares * unit_price)
            limit = max(AMOUNT_TOLERANCE_MIN, ratio * amount)
            if deviation > limit:
                row_errors.append(
                    _issue(
                        'error',
                        record,
                        'amount',
                        f'金额 {amount:.2f} 与 份额×净值 {shares * unit_price:.2f} 偏差 {deviation:.2f} 元，超出容差',
                    )
                )
            elif deviation > AMOUNT_NOISE:
                row_warnings.append(
                    _issue(
                        'warning',
                        record,
                        'amount',
                        f'金额与 份额×净值 差 {deviation:.2f} 元（手续费/四舍五入）',
                    )
                )

        order_no = record.get('order_no')
        if order_no:
            # 支付宝的订单号是**组合批次号**:同一订单跨多只基金本来就会重复(2026-09-20 实测该文件 12 条
            # 「订单号重复」全是这种误判,每一条都是真交易)。只有「同订单 + 同基金 + 同方向」才是真重复。
            key = (order_no, str(record.get('fund_code') or ''), str(record.get('type') or ''))
            if key in seen_orders:
                row_errors.append(
                    _issue(
                        'error',
                        record,
                        'orderNo',
                        f'订单号 {order_no} 与第 {seen_orders[key] or "?"} 行重复（同基金同方向）',
                    )
                )
            else:
                seen_orders[key] = record.get('row')

        if row_errors:
            errors.extend(row_errors)
            continue
        kept.append(record)
        warnings.extend(row_warnings)

    return kept, errors, warnings
