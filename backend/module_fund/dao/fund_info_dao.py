"""基金管理模块 DAO(数据访问层):基金详细信息。

写操作只 flush 不 commit,事务由 Service 层统一控制。
"""

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from module_fund.entity.do.fund_do import Fund
from common.response import PageModel
from module_fund.entity.do.fund_info_do import FundInfo
from utils.page_util import PageUtil


class FundInfoDao:
    """基金详细信息数据库操作层。"""

    # ==================== 读 ====================

    @classmethod
    async def get_info_by_code(cls, db: AsyncSession, fund_code: str) -> FundInfo | None:
        """按基金代码取详情记录(每只基金至多一行,fund_code 唯一索引)。"""
        result = await db.execute(
            select(FundInfo).where(FundInfo.fund_code == fund_code)
        )
        return result.scalars().first()

    @classmethod
    async def get_info_page(
        cls,
        db: AsyncSession,
        page_num: int,
        page_size: int,
        keyword: str | None = None,
    ) -> PageModel:
        """分页列表:窄投影(不含 info 大 JSON),join fund 带出名称与类型。

        列表只做定位与状态展示,档案键值详情由前端按 code 单查详情接口。
        """
        # autoescape:keyword 是用户输入,%/_ 会被当 LIKE 通配符,须转义
        where_clause = (
            FundInfo.fund_code.contains(keyword, autoescape=True)
            if keyword
            else True
        )
        query = (
            select(
                FundInfo.fund_info_id,
                FundInfo.fund_code,
                Fund.name.label('fund_name'),
                Fund.fund_type.label('fund_type'),
                FundInfo.create_time,
                FundInfo.update_time,
            )
            .join(Fund, Fund.code == FundInfo.fund_code, isouter=True)
            .where(where_clause)
            .order_by(FundInfo.update_time.desc().nullslast(), FundInfo.fund_info_id.desc())
        )
        return await PageUtil.paginate(
            db,
            query,
            page_num,
            page_size,
            is_page=True,
        )

    @classmethod
    async def get_all_codes(cls, db: AsyncSession) -> list[str]:
        """取表内全部基金代码(全量同步的遍历清单)。"""
        result = await db.execute(select(FundInfo.fund_code))
        return list(result.scalars().all())

    # ==================== 写 ====================

    @classmethod
    async def upsert_info(cls, db: AsyncSession, fund_code: str, info: dict) -> None:
        """按 fund_code 幂等写入详情(存在则整体覆盖 info,首次则插入)。

        Core 层 on_conflict 不触发 ORM onupdate,update_time 须显式 func.now()。
        """
        await db.execute(
            insert(FundInfo)
            .values(fund_code=fund_code, info=info)
            .on_conflict_do_update(
                index_elements=[FundInfo.fund_code],
                set_={'info': info, 'update_time': func.now()},
            )
        )

    @classmethod
    async def delete_by_code(cls, db: AsyncSession, fund_code: str) -> int:
        """按代码物理删除缓存行(删除后可重新回源),返回删除行数。"""
        result = await db.execute(
            delete(FundInfo).where(FundInfo.fund_code == fund_code)
        )
        return result.rowcount
