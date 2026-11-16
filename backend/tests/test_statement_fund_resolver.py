"""基金名称解析单测(纯函数):名称归一、去修饰词、份额后缀与歧义判定。

对齐真实场景:App 截图只有基金名,且显示名与库内规范名常差「灵活配置」「人民币」这类修饰,
A/C 份额还会同名——所以口径是「同核心词 + 同份额后缀,唯一命中才采用」。
"""

from module_portfolio.service.statement_fund_resolver import (
    core_of,
    match_candidates,
    normalize_name,
    share_suffix,
)

OWN_FUNDS = [('270042', '广发纳斯达克100ETF联接人民币(QDII)A'), ('006228', '中欧医疗创新股票A')]
FULL_TABLE = [
    ('001323', '东吴移动互联混合A'),
    ('002170', '东吴移动互联混合C'),
    ('519133', '海富通改革驱动混合'),
]


class TestNormalize:
    """名称归一:空白、全角括号差异不该影响比对。"""

    def test_blank_and_fullwidth_parentheses(self):
        assert normalize_name('  华夏 成长（混合） ') == '华夏成长(混合)'

    def test_core_drops_noise_words(self):
        assert core_of('海富通改革驱动灵活配置混合') == core_of('海富通改革驱动混合')

    def test_core_drops_qdii_and_currency_words(self):
        assert core_of('广发纳斯达克100ETF联接(QDII)A') == core_of('广发纳斯达克100ETF联接人民币(QDII)A')

    def test_share_suffix(self):
        assert share_suffix('东吴移动互联灵活配置混合A') == 'A'
        assert share_suffix('海富通改革驱动混合') == ''
        assert share_suffix('广发纳斯达克100ETF') == ''  # 末尾 F 不是份额字母


class TestMatchCandidates:
    """候选比对:同核心词 + 同份额后缀;歧义交给人工。"""

    def test_own_fund_matches_despite_missing_currency_word(self):
        hits = match_candidates('广发纳斯达克100ETF联接(QDII)A', OWN_FUNDS)
        assert [code for code, _ in hits] == ['270042']

    def test_full_table_unique_match(self):
        hits = match_candidates('海富通改革驱动灵活配置混合', FULL_TABLE)
        assert [code for code, _ in hits] == ['519133']

    def test_share_suffix_disambiguates(self):
        hits = match_candidates('东吴移动互联灵活配置混合A', FULL_TABLE)
        assert [code for code, _ in hits] == ['001323']

    def test_domestic_share_wins_when_screenshot_has_no_currency(self):
        """截图名不带币种(境内平台口径=人民币)时,不因美元份额候选而报歧义。"""
        hits = match_candidates(
            '广发纳斯达克100ETF联接(QDII)A',
            [('000055', '广发纳斯达克100ETF联接美元(QDII)A'), ('270042', '广发纳斯达克100ETF联接人民币(QDII)A')],
        )
        assert [code for code, _ in hits] == ['270042']

    def test_foreign_share_kept_when_screenshot_names_it(self):
        hits = match_candidates(
            '广发纳斯达克100ETF联接美元(QDII)A',
            [('000055', '广发纳斯达克100ETF联接美元(QDII)A'), ('270042', '广发纳斯达克100ETF联接人民币(QDII)A')],
        )
        assert [code for code, _ in hits] == ['000055']

    def test_same_core_same_suffix_still_ambiguous(self):
        """去掉币种也分不出的候选(A/C 以外的同名份额),仍要拦住交人工。"""
        hits = match_candidates(
            '某某混合A', [('111111', '某某混合A'), ('222222', '某某混合A')]
        )
        assert [code for code, _ in hits] == ['111111', '222222']

    def test_missing_share_suffix_does_not_guess(self):
        """截图没带份额字母时,不拿 A 或 C 去猜。"""
        assert match_candidates('东吴移动互联混合', FULL_TABLE) == []

    def test_no_match(self):
        assert match_candidates('不存在的基金X', FULL_TABLE) == []

    def test_empty_core_never_matches(self):
        assert match_candidates('   ', FULL_TABLE) == []
