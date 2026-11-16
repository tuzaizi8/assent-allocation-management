"""只读对账:验证恒等式「累计盈亏(快照口径) = 持有收益 + 已实现盈亏(全基金)」。

背景:持仓简况两卡的口径——
- 累计盈亏 = 最新快照 totalValue − cumulativeInvested(投资以来全部盈亏)
- 持有收益 = Σ 当前有效持仓的 profit
二者之差在业务上应等于「已实现的盈亏(含历史各轮)」。

待验证假设:已实现收益目前挂在**当前持仓行**上(realizedProfit 字段),因此只覆盖
「现在仍持有」的基金;那些**已清仓且不再持有**的基金,其历史盈亏既不在持有收益里、
也不在任何持仓行的 realizedProfit 里 —— 差额应恰好等于这部分。

只读脚本:不写任何数据。用法 .venv/bin/python scripts/reconcile_portfolio_profit.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv('.env.dev')

from sqlalchemy import select  # noqa: E402

from db.database import AsyncSessionLocal  # noqa: E402
from module_portfolio.dao.purchase_record_dao import PurchaseRecordDao  # noqa: E402
from module_portfolio.dao.redemption_record_dao import RedemptionRecordDao  # noqa: E402
from module_portfolio.entity.do.position_do import UserFundPosition  # noqa: E402
from module_portfolio.entity.do.purchase_record_do import PurchaseRecord  # noqa: E402
from module_portfolio.service.position_calc_util import fund_realized_profit  # noqa: E402
from module_portfolio.service.position_service import PositionService  # noqa: E402
from utils.redis_util import RedisUtil  # noqa: E402

USER_ID = 1


async def main() -> None:
    redis = await RedisUtil.create_redis_pool()
    try:
        async with AsyncSessionLocal() as db:
            # 1. 当前仍持有的基金(有效持仓行,del_flag='0')
            held_codes = set(
                (
                    await db.execute(
                        select(UserFundPosition.fund_code).where(
                            UserFundPosition.user_id == USER_ID,
                            UserFundPosition.del_flag == '0',
                        )
                    )
                )
                .scalars()
                .all()
            )
            # 2. 有流水记录的全部基金(含已清仓且不再持有的)
            purchase_codes = set(
                (
                    await db.execute(
                        select(PurchaseRecord.fund_code).where(
                            PurchaseRecord.user_id == USER_ID
                        )
                    )
                )
                .scalars()
                .all()
            )
            all_codes = purchase_codes | held_codes

            rows = []
            for fund_code in sorted(all_codes):
                purchases = await PurchaseRecordDao.get_purchase_records_by_fund(
                    db, USER_ID, fund_code
                )
                redemptions = await RedemptionRecordDao.get_redemption_records_by_fund(
                    db, USER_ID, fund_code
                )
                realized = fund_realized_profit(purchases, redemptions)
                rows.append((fund_code, realized, fund_code in held_codes))

            held_realized = sum(r for _, r, held in rows if held)
            cleared_realized = sum(r for _, r, held in rows if not held)

            positions = await PositionService.get_positions_services(db, redis, USER_ID)
            holding_profit = sum(p['profit'] for p in positions)
            market_value = sum(p['currentValue'] for p in positions)

            print(f'当前持仓 {len(positions)} 支 / 市值 {round(market_value, 2)}')
            print(f'持有收益(Σ当前持仓 profit)      = {round(holding_profit, 2)}')
            print(f'已实现(仍有持仓的基金)          = {round(held_realized, 2)}')
            print(f'已实现(已清仓且不再持有的基金)  = {round(cleared_realized, 2)}  ← 差额候选')
            print(f'已实现合计                      = {round(held_realized + cleared_realized, 2)}')
            print()
            print('已清仓且不再持有的基金明细(历史已实现):')
            for fund_code, realized, held in rows:
                if not held:
                    print(f'  {fund_code}  {round(realized, 2)}')
    finally:
        await redis.aclose()


if __name__ == '__main__':
    asyncio.run(main())
