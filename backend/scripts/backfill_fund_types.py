"""一次性回填脚本:把 fund 表存量的 fund_type 对齐到 AkShare fund_name_em 的真实类型。

背景:早期同步用的数据源是净值接口 fund_open_fund_daily_em——它没有类型列,只能靠基金
名称关键词猜出 4 种粗粒度类型。换成 fund_name_em 后类型由接口直接给出(34 种细粒度取值)。
本脚本按基金代码把存量行对齐到新口径;库中代码在接口结果里不存在的(如已清盘的基金)
保留原值,并把这些代码打印出来供人工确认。

用法(后端根目录执行):
    .venv/bin/python scripts/backfill_fund_types.py
"""

import asyncio
import sys
from pathlib import Path

# 以脚本方式直接执行时 sys.path[0] 是 scripts/ 而不是项目根,
# 补上项目根才能导入 module_* ——否则只有用 -m 方式运行才找得到
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import akshare as ak  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import bindparam, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

load_dotenv('.env.dev')

# 以下导入必须在 load_dotenv 之后:配置类实例化时就要读到环境变量
from config.settings import DataBaseConfig  # noqa: E402
from module_fund.entity.do.fund_do import Fund  # noqa: E402

# 分批 executemany 的批大小:避免单次语句参数过多
BATCH_SIZE = 2000


def _fetch_type_map() -> dict[str, str]:
    """拉取全量基金档案,返回 基金代码 → 基金类型 映射(同步阻塞,调用侧负责丢线程池)。"""
    df = ak.fund_name_em()
    return {str(row['基金代码']): str(row['基金类型']) for _, row in df.iterrows()}


async def main() -> None:
    type_map = await asyncio.to_thread(_fetch_type_map)
    print(f'[回填] 接口返回基金档案 {len(type_map)} 条')

    engine = create_async_engine(DataBaseConfig.async_url)
    # engine.begin() 退出即提交:全量更新统一一次事务,中途失败整体回滚
    async with engine.begin() as conn:
        rows = (await conn.execute(select(Fund.fund_id, Fund.code, Fund.fund_type))).all()
        print(f'[回填] 库中待处理 {len(rows)} 行')

        params: list[dict] = []
        unmatched: list[str] = []
        changed = 0
        for fund_id, code, old_type in rows:
            new_type = type_map.get(str(code))
            if new_type is None:
                unmatched.append(str(code))
                continue
            if new_type != old_type:
                changed += 1
            # 按主键定位而非 code:主键有索引,批量更新更快
            params.append({'b_fund_id': fund_id, 'b_type': new_type})

        stmt = (
            update(Fund)
            .where(Fund.fund_id == bindparam('b_fund_id'))
            .values(fund_type=bindparam('b_type'))
        )
        for start in range(0, len(params), BATCH_SIZE):
            await conn.execute(stmt, params[start : start + BATCH_SIZE])

    await engine.dispose()

    print(f'[回填] 已更新 {len(params)} 行,其中类型实际变化 {changed} 行')
    print(f'[回填] 未匹配(接口无此代码,保留原值) {len(unmatched)} 行')
    if unmatched:
        preview = ', '.join(unmatched[:50])
        suffix = ' ...' if len(unmatched) > 50 else ''
        print(f'[回填] 未匹配代码清单: {preview}{suffix}')


if __name__ == '__main__':
    asyncio.run(main())
