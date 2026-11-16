"""持仓模块 DAO(数据访问层):分散度规则。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from module_portfolio.entity.do.portfolio_rule_do import PortfolioRule


class PortfolioRuleDao:
    """分散度规则数据库操作层。"""

    @classmethod
    async def get_rule_by_user(cls, db: AsyncSession, user_id: int) -> PortfolioRule | None:
        """获取用户的分散度规则(一用户一条)。"""
        result = await db.execute(
            select(PortfolioRule).where(PortfolioRule.user_id == user_id)
        )
        return result.scalars().first()

    @classmethod
    async def add_rule_dao(cls, db: AsyncSession, rule: PortfolioRule) -> PortfolioRule:
        """新增规则(flush 回填自增主键)。"""
        db.add(rule)
        await db.flush()
        return rule
