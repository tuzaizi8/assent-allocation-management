"""基金净值历史 DAO(数据访问层)。

一行一只基金,nav_data 存一份完整数据,收益率走势与净值走势两套视图按需读不同字段。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from module_fund.entity.do.fund_do import Fund
from module_fund.entity.do.fund_nav_do import FundNavHistory
from module_fund.entity.vo.fund_vo import FundNavQueryModel
from utils.nav_window_util import window_start
from utils.page_util import PageModel, PageUtil


class FundNavDao:
    """基金净值历史数据库操作层。"""

    @classmethod
    async def get_nav_history(cls, db: AsyncSession, fund_code: str) -> Optional[list[dict]]:
        """获取基金净值记录列表(nav_data.records),未命中返回 None。"""
        result = await db.execute(select(FundNavHistory).where(FundNavHistory.fund_code == fund_code))
        record = result.scalars().first()
        if record and record.nav_data and 'records' in record.nav_data:
            return record.nav_data['records']
        return None

    @classmethod
    async def upsert_nav_history(
        cls, db: AsyncSession, fund_code: str, records: list[dict], source: str = 'akshare'
    ) -> None:
        """写入或更新净值历史(只 flush,事务由调用方 Service 控制)。

        同步维护 latest_date/record_count 元数据冗余列——列表页窄投影与三态
        同步状态的 SQL 谓词依赖它们,读路径因此不必解析 nav_data 大 JSON。
        """
        nav_data = {'source': source, 'records': records}
        # 最新净值日取自末条记录(序列按日期升序);格式异常置 None,不影响主数据落库
        latest_date = None
        if records:
            latest_str = records[-1].get('nav_date')
            try:
                latest_date = datetime.strptime(str(latest_str), '%Y-%m-%d').date()
            except (ValueError, TypeError):
                latest_date = None
        result = await db.execute(select(FundNavHistory).where(FundNavHistory.fund_code == fund_code))
        existing = result.scalars().first()
        if existing:
            existing.nav_data = nav_data
            existing.latest_date = latest_date
            existing.record_count = len(records)
        else:
            db.add(FundNavHistory(
                fund_code=fund_code,
                nav_data=nav_data,
                latest_date=latest_date,
                record_count=len(records),
            ))
        await db.flush()

    @classmethod
    async def is_nav_stale(cls, db: AsyncSession, fund_code: str) -> bool:
        """判断净值数据是否过期(双窗口失效:00:00/22:00 两个失效点)。

        新鲜 = 已有今天的净值 OR 今天当前窗口内已回源尝试过——
        akshare 净值晚间集中发布,22 点后的首次访问即回源拉取当日数据,
        白天判新鲜(数据源本来就没有更新的);窗口划分见 NAV_REFRESH_DEADLINE_HOUR。
        """
        result = await db.execute(select(FundNavHistory).where(FundNavHistory.fund_code == fund_code))
        record = result.scalars().first()
        if not record or not record.nav_data or 'records' not in record.nav_data:
            return True
        records = record.nav_data['records']
        if not records:
            return True
        latest_date_str = records[-1].get('nav_date')
        if not latest_date_str:
            return True
        try:
            latest_date = datetime.strptime(str(latest_date_str), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            try:
                latest_date = datetime.strptime(str(latest_date_str), '%Y%m%d').date()
            except (ValueError, TypeError):
                return True
        if latest_date >= datetime.now().date():
            return False
        if record.update_time is None:
            return True
        # 判定用本地时间(与写入侧 datetime.now 同一时区基准)
        return record.update_time < window_start(datetime.now())

    @classmethod
    async def get_nav_page(cls, db: AsyncSession, query_object: FundNavQueryModel) -> PageModel:
        """净值行分页列表(窄投影:绝不取 nav_data 大 JSON,元数据走冗余列)。

        三态同步状态在 SQL 下推:'1'已同步(最新净值日≥今天 或 当前窗口内已回源,双窗口 00:00/22:00)/
        '2'已过期(其余);'0'未同步的基金不在本表,传'0'自然返回空页。
        LEFT JOIN fund 仅取名称——同步的基金代码可能不在 fund 表(如已清盘),用左连不丢行。
        """
        # 三态判定与 is_nav_stale 同一口径(双窗口),窗口起点查询时用 Python 计算作绑定参数,
        # 免写 SQL 方言的 CASE WHEN,跨库一致
        fresh = or_(
            FundNavHistory.latest_date >= func.current_date(),
            FundNavHistory.update_time >= window_start(datetime.now()),
        )
        status_predicates = {
            '1': fresh,
            '2': ~fresh,
            # '0'(未同步)在净值表域内恒为空:未同步基金的转化入口是页面的空态同步
            '0': false(),
        }
        query = (
            select(
                FundNavHistory.fund_nav_id,
                FundNavHistory.fund_code,
                Fund.name.label('fund_name'),
                FundNavHistory.latest_date,
                FundNavHistory.record_count,
                FundNavHistory.update_time,
            )
            .join(Fund, Fund.code == FundNavHistory.fund_code, isouter=True)
            .where(
                FundNavHistory.fund_code.like(f'%{query_object.fund_code}%') if query_object.fund_code else True,
                Fund.name.like(f'%{query_object.fund_name}%') if query_object.fund_name else True,
                status_predicates.get(query_object.sync_status, True) if query_object.sync_status else True,
            )
            .order_by(FundNavHistory.update_time.desc(), FundNavHistory.fund_nav_id.desc())
        )
        return await PageUtil.paginate(
            db, query, query_object.page_num, query_object.page_size, is_page=True
        )
