"""基金名称 → 基金代码解析(App 交易记录截图只有基金名、没有代码,只能按名称认)。

匹配优先级(宁可拦住,不猜错):
1. 用户自己的基金(持仓涉及的 fund_code,含已清仓):先在这里找——同一只基金 App 显示名
   常省略「人民币」这类修饰,而库里是自己的持仓名,最可靠;
2. 全库按核心词模糊;
3. 两处都要求「同核心词 + 同份额后缀」,且只取唯一命中;多个候选(A/C 份额并存)一律留空,
   把候选清单写进 resolve_note,由校验层拦成 error 交人工核对。
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from module_fund.dao.fund_dao import FundDao
from module_portfolio.dao.position_dao import PositionDao
from utils.log import logger

# 平台显示名与库内规范名的常见差异:去噪后仍要唯一命中才采用
NOISE_WORDS = ('灵活配置', '发起式', '联接', '人民币', '美元', '现汇', 'QDII', '（QDII）', '(QDII)')
# 币种判别:截图名没标币种时按境内平台口径取人民币份额,外币份额只有截图写明才认
# 份额后缀字母(末尾 A/C 这类);不含 F,否则「…ETF」会被当成份额后缀
SHARE_SUFFIXES = frozenset('ABCDEHIORY')


def normalize_name(name: str) -> str:
    """去空白、统一全角括号,得到可比较的名称。"""
    return re.sub(r'\s+', '', str(name or '')).replace('（', '(').replace('）', ')')


def _raw_suffix(text: str) -> str:
    """末尾份额字母(认不出为空串);不含 F,否则「…ETF」会被当成份额后缀。"""
    match = re.search(r'([A-Z])$', text)
    return match.group(1) if match and match.group(1) in SHARE_SUFFIXES else ''


def core_of(name: str) -> str:
    """核心词:剔掉修饰词与末尾份额字母后的骨架,用于跨平台表述差异比对。

    份额字母单列判断(见 share_suffix),不参与核心词比对——否则「…混合」与库里的「…混合A」
    核心词不相等,永远匹配不上。
    """
    text = normalize_name(name)
    for word in NOISE_WORDS:
        text = text.replace(word, '')
    text = text.replace('()', '')
    suffix = _raw_suffix(text)
    return text[: -len(suffix)] if suffix else text


def share_suffix(name: str) -> str:
    """份额后缀(末尾份额字母,如 A/C);认不出为空串。"""
    return _raw_suffix(normalize_name(name))


def currency_of(name: str) -> str:
    """币种标记:人民币 / 美元 / 空(未标注);与份额后缀一样是判别项,不参与核心词比对。"""
    text = normalize_name(name)
    if '人民币' in text:
        return '人民币'
    if '美元' in text or '现汇' in text:
        return '美元'
    return ''


def match_candidates(name: str, candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """候选里与截图名「同核心词 + 同份额后缀」的那些(0 个=没认出来,多个=歧义)。"""
    core = core_of(name)
    if not core:
        return []
    suffix = share_suffix(name)
    matched = [
        (code, fund_name)
        for code, fund_name in candidates
        if core_of(fund_name) == core and share_suffix(fund_name) == suffix
    ]
    wanted = currency_of(name)
    if wanted:
        return [item for item in matched if currency_of(item[1]) == wanted] or matched
    # 截图没标币种(如「广发纳斯达克100ETF联接(QDII)A」)时按境内平台口径取人民币份额
    domestic = [item for item in matched if currency_of(item[1]) in ('', '人民币')]
    return domestic or matched


def _ambiguous_note(hits: list[tuple[str, str]]) -> str:
    return '匹配到多个候选，请人工确认：' + ' / '.join(f'{code} {name}' for code, name in hits[:5])


async def resolve_fund_codes(db: AsyncSession, user_id: int, records: list[dict]) -> None:
    """就地补 fund_code / fund_name(换成库内规范名)/ resolve_note;只处理没有代码的记录。"""
    targets = [record for record in records if not record.get('fund_code') and record.get('fund_name')]
    if not targets:
        return

    own_codes = [position.fund_code for position in await PositionDao.get_all_positions(db, user_id)]
    own_funds = await FundDao.get_funds_by_codes(db, own_codes)

    resolved = 0
    for record in targets:
        hits = match_candidates(record['fund_name'], own_funds)
        source = '按你持仓的基金匹配'
        if not hits:
            hits = match_candidates(
                record['fund_name'], await FundDao.search_funds_by_name(db, core_of(record['fund_name']))
            )
            source = '全库匹配'
        if len(hits) == 1:
            record['fund_code'], record['fund_name'] = hits[0]
            record['resolve_note'] = source
            resolved += 1
        else:
            record['resolve_note'] = _ambiguous_note(hits) if hits else '未匹配到基金，请核对名称'

    logger.info(f'[导入] 名称解析基金代码 待解析={len(targets)} 命中={resolved} 文件记录数={len(records)}')
