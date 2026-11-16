"""分散度规则 Service(业务逻辑层)。

职责:用户分散度规则的查询与创建/更新(一用户一条,无记录返回默认值)。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from common.response import CrudResponseModel
from module_portfolio.dao.portfolio_rule_dao import PortfolioRuleDao
from module_portfolio.entity.do.portfolio_rule_do import PortfolioRule
from module_portfolio.entity.vo.position_vo import PortfolioRuleModel
from utils.log import logger


class PortfolioRuleService:
    """分散度规则服务层。"""

    @classmethod
    async def get_rules_services(cls, query_db: AsyncSession, user_id: int) -> PortfolioRuleModel:
        """获取用户分散度规则(无记录返回默认值)。"""
        rule = await PortfolioRuleDao.get_rule_by_user(query_db, user_id)
        if not rule:
            return PortfolioRuleModel()
        return PortfolioRuleModel(
            max_single_fund_ratio=float(rule.max_single_fund_ratio),
            max_equity_ratio=float(rule.max_equity_ratio),
            max_bond_ratio=float(rule.max_bond_ratio),
            max_hybrid_ratio=float(rule.max_hybrid_ratio),
            max_money_ratio=float(rule.max_money_ratio),
        )

    @classmethod
    async def update_rules_services(
        cls, query_db: AsyncSession, user_id: int, rule_model: PortfolioRuleModel
    ) -> CrudResponseModel:
        """创建或更新分散度规则。"""
        try:
            rule = await PortfolioRuleDao.get_rule_by_user(query_db, user_id)
            if rule:
                rule.max_single_fund_ratio = rule_model.max_single_fund_ratio
                rule.max_equity_ratio = rule_model.max_equity_ratio
                rule.max_bond_ratio = rule_model.max_bond_ratio
                rule.max_hybrid_ratio = rule_model.max_hybrid_ratio
                rule.max_money_ratio = rule_model.max_money_ratio
            else:
                await PortfolioRuleDao.add_rule_dao(
                    query_db,
                    PortfolioRule(
                        user_id=user_id,
                        max_single_fund_ratio=rule_model.max_single_fund_ratio,
                        max_equity_ratio=rule_model.max_equity_ratio,
                        max_bond_ratio=rule_model.max_bond_ratio,
                        max_hybrid_ratio=rule_model.max_hybrid_ratio,
                        max_money_ratio=rule_model.max_money_ratio,
                    ),
                )
            await query_db.commit()
            logger.info(f'[规则] 更新成功 user_id={user_id}')
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[规则] 更新失败回滚 user_id={user_id} | {e}')
            raise e
