"""幂等迁移脚本:持仓头表列序调整(fund_code 移回 user_id 之后)。

背景:fund_code 由 fund_id 迁移而来,当时用 ADD COLUMN 追加到了表尾;
PostgreSQL 不支持 ADD COLUMN AFTER,本脚本按「建新表 → 拷数据 → 序列对齐
→ 删旧表 → 改名」重建表,把 fund_code 放回原 fund_id 的位置(user_id 之后、
status 之前)。单事务执行,失败自动回滚,存量数据零损失。

全部可重跑(重复执行无副作用):
- 表不存在(全新库) → 交给建表流程,直接退出
- fund_code 的 ordinal_position 已是期望位置(position_id=1, user_id=2, fund_code=3)
  → 打印「列序已就绪」直接退出
- 否则重建

列定义与 position_do.py / db/base_model.py 逐字段对齐
(status/del_flag 带 server_default;审计五列无 server_default,由 ORM 端 default 填充)。

用法(后端根目录执行):
    .venv/bin/python scripts/migrate_position_column_order.py
"""

import asyncio
import sys
from pathlib import Path

# 以脚本方式直接执行时 sys.path[0] 是 scripts/ 而不是项目根,
# 补上项目根才能导入 config ——否则只有用 -m 方式运行才找得到
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

load_dotenv('.env.dev')

# 以下导入必须在 load_dotenv 之后:配置类实例化时就要读到环境变量
from config.settings import DataBaseConfig  # noqa: E402

TABLE_EXISTS_SQL = "SELECT to_regclass('user_fund_positions') IS NOT NULL"
FUND_CODE_ORDINAL_SQL = """
SELECT ordinal_position FROM information_schema.columns
WHERE table_name = 'user_fund_positions' AND column_name = 'fund_code'
"""
# 期望位:position_id=1, user_id=2, fund_code=3(与 DO 声明顺序一致)
EXPECTED_ORDINAL = 3

# 逐字段对齐 position_do.py + BaseModel(status/del_flag 有 server_default,
# 审计列没有——由 ORM 端 default 填充,照抄现状避免与 create_all 形态漂移)
CREATE_NEW_TABLE_SQL = """
CREATE TABLE user_fund_positions_new (
    position_id BIGSERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    fund_code   VARCHAR(20) NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT '0',
    del_flag    CHAR(1) DEFAULT '0',
    create_by   VARCHAR(64) DEFAULT '',
    create_time TIMESTAMP,
    update_by   VARCHAR(64) DEFAULT '',
    update_time TIMESTAMP,
    remark      VARCHAR(500) DEFAULT ''
)
"""

COPY_DATA_SQL = """
INSERT INTO user_fund_positions_new
    (position_id, user_id, fund_code, status, del_flag,
     create_by, create_time, update_by, update_time, remark)
SELECT position_id, user_id, fund_code, status, del_flag,
       create_by, create_time, update_by, update_time, remark
FROM user_fund_positions
ORDER BY position_id
"""

# 序列追到存量最大主键之后,新写入不自撞
ALIGN_SEQUENCE_SQL = """
SELECT setval(
    pg_get_serial_sequence('user_fund_positions_new', 'position_id'),
    (SELECT COALESCE(MAX(position_id), 0) FROM user_fund_positions_new) + 1,
    false
)
"""

CREATE_INDEX_SQL = (
    "CREATE INDEX idx_position_user_fund "
    "ON user_fund_positions (user_id, fund_code)"
)

TABLE_COMMENT_SQL = "COMMENT ON TABLE user_fund_positions_new IS '用户基金持仓头表'"
COLUMN_COMMENTS_SQL = [
    ("position_id", "持仓主键"),
    ("user_id", "用户ID(逻辑关联 sys_user.user_id)"),
    ("fund_code", "基金代码(逻辑关联 fund.code,无外键)"),
    ("status", "持仓状态(0正常 1部分赎回 2全部赎回,字典 sys_position_status)"),
    ("del_flag", "删除标志(0存在 2删除,全额赎回后软删)"),
    ("create_by", "创建者"),
    ("create_time", "创建时间"),
    ("update_by", "更新者"),
    ("update_time", "更新时间"),
    ("remark", "备注"),
]

DROP_OLD_TABLE_SQL = "DROP TABLE user_fund_positions"
RENAME_TABLE_SQL = "ALTER TABLE user_fund_positions_new RENAME TO user_fund_positions"


async def main() -> None:
    if DataBaseConfig.db_type != 'postgresql':
        print(f'[迁移] 当前数据库类型 {DataBaseConfig.db_type} 不支持本脚本语法,终止')
        return

    engine = create_async_engine(DataBaseConfig.async_url)
    async with engine.begin() as conn:
        table_exists = (await conn.execute(text(TABLE_EXISTS_SQL))).scalar()
        if not table_exists:
            print('[迁移] user_fund_positions 表不存在(全新库),无需迁移,交给建表流程')
            await engine.dispose()
            return

        # fund_code 尚未存在说明 fund_id → fund_code 的前置迁移还没跑,顺序不能颠倒
        ordinal = (
            await conn.execute(text(FUND_CODE_ORDINAL_SQL))
        ).scalar()
        if ordinal is None:
            print('[迁移] 中止:fund_code 列不存在,请先执行 scripts/migrate_position_fund_code.py')
            await engine.dispose()
            return
        if ordinal == EXPECTED_ORDINAL:
            print(f'[迁移] fund_code 列序已就绪(第 {ordinal} 列),无需重建')
            await engine.dispose()
            return
        print(f'[迁移] ① 当前 fund_code 在第 {ordinal} 列(表尾),开始重建表')

        await conn.execute(text(CREATE_NEW_TABLE_SQL))
        copied = (await conn.execute(text(COPY_DATA_SQL))).rowcount
        print(f'[迁移] ② 数据拷贝完成,{copied} 行(空表为 0 属正常)')

        await conn.execute(text(ALIGN_SEQUENCE_SQL))
        await conn.execute(text(TABLE_COMMENT_SQL))
        for column, comment in COLUMN_COMMENTS_SQL:
            await conn.execute(
                text(f"COMMENT ON COLUMN user_fund_positions_new.{column} IS '{comment}'")
            )
        print('[迁移] ③ 序列对齐 + 表列注释重建完成')

        await conn.execute(text(DROP_OLD_TABLE_SQL))
        await conn.execute(text(RENAME_TABLE_SQL))
        print('[迁移] ④ 旧表已删,新表改名完成')

        # 索引名 schema 内全局唯一,必须等旧表(带着旧索引)删除后再建
        await conn.execute(text(CREATE_INDEX_SQL))
        print('[迁移] ⑤ 索引 idx_position_user_fund(user_id, fund_code) 重建完成')

    await engine.dispose()
    print('[迁移] 完成;本次仅调列序、不涉代码依赖,可直接重启后端验证')
    print(r'[迁移] 校验:psql 里 \d user_fund_positions 确认列序与 idx_position_user_fund')


if __name__ == '__main__':
    asyncio.run(main())
