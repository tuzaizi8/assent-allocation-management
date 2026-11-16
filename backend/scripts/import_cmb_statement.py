"""一次性导入:招商银行基金交易 Excel 走服务层 preview → confirm 落库。

绕过 HTTP 层(限流/登录态),但**完全复用 app 的导入链路**:校验拦截 → 按平台(generic)判重
合并 → 全量重建持仓 → 重建快照。可重复执行:已导入的行会被判重跳过。
用法: .venv/bin/python scripts/import_cmb_statement.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv('.env.dev')

from db.database import AsyncSessionLocal  # noqa: E402
from module_portfolio.entity.vo.excel_vo import (  # noqa: E402
    ImportTransactionRecordModel,
    TransactionConfirmModel,
)
from module_portfolio.service.statement_import_service import (  # noqa: E402
    StatementImportService,
)
from utils.log import logger  # noqa: E402
from utils.redis_util import RedisUtil  # noqa: E402

XLSX_PATH = Path('/Users/tuzaizi/Desktop/招商银行_基金交易模板.xlsx')
USER_ID = 1


async def main() -> None:
    content = XLSX_PATH.read_bytes()
    preview = await StatementImportService.preview_transaction_import_services(
        None, None, 0, content, XLSX_PATH.name
    )
    summary = preview['summary']
    logger.info(
        f'预览: 适配器={summary["adapter"]} 买入={summary["purchases"]} '
        f'赎回={summary["redemptions"]} 告警={summary["warnings"]} 拦截={len(preview["errors"])}'
    )
    for issue in preview['errors']:
        logger.warning(f'拦截行: {issue}')
    if preview['errors']:
        raise SystemExit('存在 error 级校验问题,按 app 口径拒绝落库')

    records = [ImportTransactionRecordModel.model_validate(row) for row in preview['preview']]
    confirm_model = TransactionConfirmModel(
        confirmed=True, adapter=summary['adapter'], records=records
    )
    redis = await RedisUtil.create_redis_pool()
    try:
        async with AsyncSessionLocal() as db:
            result = await StatementImportService.confirm_transaction_import_services(
                db, redis, USER_ID, confirm_model
            )
        print('导入回执:', {k: result.get(k) for k in ('success', 'imported', 'positionsCreated', 'snapshotRebuilt', 'snapshotRebuildMessage')})
        if result.get('errors'):
            print('逐条失败:', result['errors'])
    finally:
        await redis.aclose()


if __name__ == '__main__':
    asyncio.run(main())
