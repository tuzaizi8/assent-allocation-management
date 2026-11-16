"""一次性修数脚本:把被误判成买入的「定投卖出」改成赎回,并清掉因此僵尸化的持仓。

背景(2026-09-22 使用者报「卖出被识别成买入」):蚂蚁(支付宝)「基金交易明细」里的业务类型
「定投卖出」同时含买入词「定投」与卖出词「卖」,而买卖方向判定原先**先查买入词** → 判成买入。
实测那份 78 页明细里这类行只有 2 条:
    013577  2023-10-10  1.11 份 / 1.18 元(源文件原文「定投卖出」)—— 该基金此后已清仓
    014097  2024-02-06  2.68 份 / 2.88 元(= 先前的 1.20 + 1.48,该基金全部份额)
后果:买入流水凭空多一条、赎回流水少一条 → 这两只基金的持仓永远清不掉(份额虚高、收益曲线偏高),
而接口返回的是成功,界面上完全看不出来。

代码侧根因已修(`statement_adapters._resolve_type` 与 `statement_validators.direction_of` 改为
**卖出词优先**);本脚本只负责把已经写错的数据改回来。

每笔的做法:
  ① 按 (基金代码, 买入日期, 份额) 三元组定位那一条错向买入行 —— 必须恰好命中 1 行,否则不猜、直接退出;
  ② 打印整行备份 + 可直接粘回的回滚 INSERT(改前);
  ③ 删掉那条买入行;
  ④ 走既有 `PositionService.add_redemption_services` 写赎回行(赎回份额取**持仓剩余**并与源文件
     卖出份额校验一致、日期与源文件一致):它自带
     「赎回份额 ≤ 持有份额」与「赎回日 ≥ 首次买入日」两道防呆、按当日净值换算,并在全额赎回时
     置 status='2' + 软删持仓 + 增量补快照 —— 正是「全额赎回」应有的一整套动作;
  ⑤ 打印改后状态(持仓 status/del_flag + 该基金全部流水),最后触发一次快照全量重建。

赎回行备注保留原买入行的 `导入:<平台>:` 前缀(该前缀是「下次导入判重」的作用域锚,丢了它下次
重导同一份文件会把这条卖出再导一次),只把后半段换成 `修正:定投卖出曾被误判为买入`。

可重跑(重复执行无副作用):该买入行已不存在、且同日期同份额的赎回行已存在 → 打印「已是赎回」跳过。

回滚:改前打印的那条 INSERT 可直接粘回;等价的说法是
    DELETE FROM redemption_records WHERE fund_code = '013577' AND redemption_date = '2023-10-10'
      AND remark LIKE '%修正:定投卖出曾被误判为买入%';
    <粘回改前打印的 INSERT INTO purchase_records ...>
    UPDATE user_fund_positions SET status = '0', del_flag = '0' WHERE position_id IN (...);
    -- 再到「快照管理」点一次「重建快照」

用法(后端根目录执行):
    .venv/bin/python scripts/fix_misparsed_sell_direction.py
"""

import asyncio
import os
import sys
from datetime import date
from pathlib import Path

# 以脚本方式直接执行时 sys.path[0] 是 scripts/ 而不是项目根,
# 补上项目根才能导入 config —— 否则只有用 -m 方式运行才找得到
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv('.env.dev')

# 以下导入必须在 load_dotenv 之后:配置类实例化时就要读到环境变量
from sqlalchemy import text  # noqa: E402

from db.database import AsyncSessionLocal  # noqa: E402
from module_portfolio.dao.purchase_record_dao import PurchaseRecordDao  # noqa: E402
from module_portfolio.dao.redemption_record_dao import RedemptionRecordDao  # noqa: E402
from module_portfolio.entity.vo.position_vo import RedemptionRecordCreateModel  # noqa: E402
from module_portfolio.service.position_service import PositionService  # noqa: E402
from module_portfolio.service.snapshot_service import SnapshotService  # noqa: E402
from utils.redis_util import RedisUtil  # noqa: E402

FIX_NOTE = '修正:定投卖出曾被误判为买入'
# 份额比较容差:库里是 numeric,与源文件的小数位比对不能靠浮点严格相等
SHARES_TOLERANCE = 1e-6

# (基金代码, 错向买入的日期, 份额, 源文件里的原始行) —— 三元组定位,不写死 id
TARGETS = (
    ('013577', date(2023, 10, 10), 1.11, '定投卖出 1.11 份 / 1.18 元'),
    ('014097', date(2024, 2, 6), 2.68, '定投卖出 2.68 份 / 2.88 元'),
)

SELECT_BUY = text(
    'SELECT purchase_id, position_id, user_id, fund_code, shares, cost_price, '
    'purchase_date, status, amount, remark '
    'FROM purchase_records WHERE fund_code = :code AND purchase_date = :day'
)
SELECT_SELL = text(
    'SELECT redemption_id, position_id, user_id, fund_code, shares, nav_price, '
    'redemption_date, status, amount, remark '
    'FROM redemption_records WHERE fund_code = :code AND redemption_date = :day'
)
SELECT_STATE = text(
    'SELECT p.position_id, p.status, p.del_flag, '
    '(SELECT count(*) FROM purchase_records b WHERE b.position_id = p.position_id) AS buys, '
    '(SELECT count(*) FROM redemption_records r WHERE r.position_id = p.position_id) AS sells '
    'FROM user_fund_positions p WHERE p.fund_code = :code ORDER BY p.position_id'
)
DELETE_BUY = text('DELETE FROM purchase_records WHERE purchase_id = :pid')


def sql_value(value: object) -> str:
    """把行里的值拼成可粘回的 SQL 字面量(字符串转义单引号)。"""
    if value is None:
        return 'NULL'
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def rollback_sql(row) -> str:
    """改前把原行打成一条 INSERT —— 回滚靠它,不靠记忆。"""
    columns = (
        'purchase_id, position_id, user_id, fund_code, shares, cost_price, '
        'purchase_date, status, amount, remark'
    )
    values = ', '.join(
        sql_value(row[name])
        for name in (
            'purchase_id',
            'position_id',
            'user_id',
            'fund_code',
            'shares',
            'cost_price',
            'purchase_date',
            'status',
            'amount',
            'remark',
        )
    )
    return f'INSERT INTO purchase_records ({columns}) VALUES ({values});'


def fix_remark(original: str | None) -> str:
    """保留原备注的 `导入:<平台>: <基金名>`(判重作用域的锚),后半段换成修正说明。"""
    base = (original or '').split(' | ')[0].strip()
    note = f'{FIX_NOTE}({date.today().isoformat()})'
    return f'{base} | {note}' if base else note


async def locate_wrong_purchase(db, fund_code: str, day: date, shares: float):
    """定位那条错向买入行;命中恰好 1 行才返回,否则报错退出(不猜)。"""
    rows = (await db.execute(SELECT_BUY, {'code': fund_code, 'day': day})).mappings().all()
    matched = [row for row in rows if abs(float(row['shares']) - shares) < SHARES_TOLERANCE]
    if len(matched) == 1:
        return matched[0]
    if rows:
        raise SystemExit(
            f'[修数] {fund_code} {day} 该日有 {len(rows)} 行买入,按份额 {shares} 命中 {len(matched)} 行'
            ' → 不猜,人工核对后再跑'
        )
    return None


async def already_redeemed(db, fund_code: str, day: date, shares: float) -> bool:
    rows = (await db.execute(SELECT_SELL, {'code': fund_code, 'day': day})).mappings().all()
    return any(abs(float(row['shares']) - shares) < SHARES_TOLERANCE for row in rows)


async def repair_one(db, redis, fund_code: str, day: date, shares: float, source_note: str) -> int | None:
    """改一笔;返回 user_id(本次真改了)或 None(已是赎回 / 无需改)。"""
    wrong = await locate_wrong_purchase(db, fund_code, day, shares)
    if wrong is None:
        if await already_redeemed(db, fund_code, day, shares):
            print(f'[修数] {fund_code} {day} 已是赎回 {shares} 份 → 跳过(可重跑)')
            return None
        raise SystemExit(
            f'[修数] {fund_code} {day} 既没有 {shares} 份的买入行、也没有对应赎回行'
            ' → 数据形态与预期不符,人工核对'
        )

    user_id = int(wrong['user_id'])
    print(f'\n=== 修正 {fund_code} {day} {shares} 份(源文件:{source_note}) ===')
    print(f'[改前] 错向买入行: {dict(wrong)}')
    print(f'[改前] 回滚 SQL: {rollback_sql(wrong)}')

    await db.execute(DELETE_BUY, {'pid': wrong['purchase_id']})
    await db.flush()  # 让下面的服务在同一事务里看到这行已删(份额校验与全额判定都靠它)

    # 赎回份额按**持仓剩余**给,而不是直接给源文件的 2.68:服务内部用 float 累加算剩余
    # (1.2 + 1.48 = 2.6799999999999997),源文件的 2.68 比它大一个浮点尾巴,会被
    # 「赎回份额超过持有份额」拦下 —— 是表示误差,不是真超。两者本应相等(容差 0.01,
    # 与服务的全额赎回阈值同量级),不相等就停下来人工核。
    position_id = int(wrong['position_id'])
    buys = await PurchaseRecordDao.get_purchase_records(db, position_id)
    sells = await RedemptionRecordDao.get_redemption_records(db, position_id)
    remaining = sum(float(row.shares) for row in buys) - sum(float(row.shares) for row in sells)
    if abs(remaining - shares) > 0.01:
        raise SystemExit(
            f'[修数] {fund_code} {day} 源文件卖出 {shares} 份,但持仓剩余 {remaining:.4f} 份'
            f'(差 {remaining - shares:+.4f}) → 不是全额赎回或数据形态不符,人工核对'
        )
    print(f'[口径] 源文件卖出 {shares} 份 = 持仓剩余 {remaining:.4f} 份 → 按剩余份额全额赎回')

    page_object = RedemptionRecordCreateModel(
        fund_code=fund_code,
        shares=remaining,
        redemption_date=day,
        remark=fix_remark(wrong['remark']),
    )
    result = await PositionService.add_redemption_services(db, redis, user_id, page_object)
    print(f'[改后] 赎回行: {result}')
    print(f'[改后] 赎回行备注: {fix_remark(wrong["remark"])}')
    return user_id


async def print_state(db, fund_code: str) -> None:
    rows = (await db.execute(SELECT_STATE, {'code': fund_code})).mappings().all()
    for row in rows:
        print(
            f'[状态] {fund_code} position={row["position_id"]} status={row["status"]} '
            f'del_flag={row["del_flag"]} 买入 {row["buys"]} 条 / 赎回 {row["sells"]} 条'
        )


async def rebuild_snapshots(db, redis, user_id: int) -> None:
    try:
        stats = await SnapshotService.rebuild_from_transactions_services(db, redis, user_id)
        print(f'[修数] 快照全量重建完成 user_id={user_id} {stats}')
    except Exception as exc:  # 记录已修正,派生数据失败只提示、不倒回去
        print(f'[修数] 记录已修正,但快照全量重建未完成({exc});请到「快照管理」点一次「重建快照」')


async def main() -> None:
    redis = await RedisUtil.create_redis_pool()
    users: set[int] = set()
    try:
        async with AsyncSessionLocal() as db:
            for fund_code, day, shares, source_note in TARGETS:
                user_id = await repair_one(db, redis, fund_code, day, shares, source_note)
                if user_id is not None:
                    users.add(user_id)
            print()
            for fund_code, _, _, _ in TARGETS:
                await print_state(db, fund_code)
            for user_id in sorted(users):
                await rebuild_snapshots(db, redis, user_id)
    finally:
        await redis.aclose()
    print('\n[修数] 完成。回滚方式见脚本头注释;两只基金应从持仓列表消失。')
    # 收尾必须显式退进程:import PositionService 会连带 import akshare_service,后者在导入期
    # 创建 V8(MiniRacer)平台并留下非守护线程 —— 正常退出会在解释器 finalize 阶段等它们 join
    # 而**永久卡住**(实测卡 6 分钟以上)。此时写库已提交、Redis 已关,直接退。
    sys.stdout.flush()
    os._exit(0)


if __name__ == '__main__':
    asyncio.run(main())
