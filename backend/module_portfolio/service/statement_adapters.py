"""平台适配配置(YAML)加载、选择与字段抽取。

平台差异全部落在项目根目录(与 .env.dev 同级)的 *.yaml 里:新增平台 = 复制一份 YAML,
改字段别名与指纹,不用改代码。本模块只做三件事:

1. 启动期(on import)加载根目录全部 YAML,校验必填项,坏配置当场 fail-fast(含文件名与字段名);
2. detect_adapter:按「平台指纹命中数 → 表头命中列数」打分选适配器,零命中回落 generic;
3. extract_records:table 模式走「表头行 → 列名映射」(不依赖列号,加列挪列不改代码),
   labelValue 模式走「逐块就近取值」(卡片式 PDF 对账单),
   listItem 模式走「方向词开新条 + 后续行归入本条」(App 交易记录列表截图:无表头、无代码、无份额)。

抽取只负责"把字读出来",不判断对错:日期读不出来就留空,让 statement_validators 分级报错。
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from exceptions.exceptions import ServiceWarning
from module_portfolio.service.statement_readers import DocumentContent, DocumentTable, LAYER_TEXT
from utils.log import logger

DEFAULT_ADAPTER_KEY = 'generic'
MODE_TABLE = 'table'
MODE_LABEL_VALUE = 'labelValue'
MODE_LIST_ITEM = 'listItem'
MODES = (MODE_TABLE, MODE_LABEL_VALUE, MODE_LIST_ITEM)

# fields 里允许出现的字段名:写错了当场报错,不静默丢字段
FIELD_ORDER = (
    'orderNo', 'date', 'fundCode', 'fundName', 'type',
    # 申请金额:与申请份额**成对**出现(蚂蚁明细 col6/col7),是「类型列认不出」时分清买卖两条腿的关键
    'applyAmount', 'applyShares',
    'shares', 'amount', 'unitPrice', 'fee',
)
KNOWN_FIELDS = frozenset(FIELD_ORDER)
# 没有这两列就不成单
REQUIRED_FIELDS = ('date', 'fundCode')
# 买卖方向的三个来源:显式类型列 / 申请份额是否为空 / 确认份额
DIRECTION_FIELDS = ('type', 'applyShares', 'shares')

# 「转入」补进来:与 SELL_WORDS 的「转出」对称——「转换转入」这类写法原本只能掉进申请列兜底赌方向
BUY_WORDS = ('买', '申购', '认购', '定投', '转换入', '转入')
# 「转出」补进来:转换转出 / 转托管转出这类写法原本只能靠申请份额兜底猜方向
SELL_WORDS = ('卖', '赎回', '转换出', '转出')
# 分红行的两种归一化标签。**不新增记录类型**:分红统一落在买入/赎回表里(份额不动的现金分红记成
# 「0 份额 + 负金额买入」),这两条标签就是持久化的区分依据(预览页徽标 + 落库备注都取它)。
DIVIDEND_REINVEST = '红利再投资'
DIVIDEND_CASH = '现金分红'
# 重复出现即视为下一条记录开始(卡片式对账单一块一笔)
RECORD_KEY_FIELDS = ('orderNo', 'fundCode')

# 列表式金额必须带货币标记(前缀 ¥ 或后缀 元/¥):基金名称里带数字(如 纳斯达克100ETF),
# 不能取「第一个数字」
_AMOUNT_RE = re.compile(r'[¥￥]\s*(-?\d[\d,]*(?:\.\d+)?)|(-?\d[\d,]*(?:\.\d+)?)\s*[元¥￥]')
# 列表式份额同principle:必须带单位(「30.97份」)才算,单位由适配器 share_units 声明
_NUMBER_TEXT = r'-?\d[\d,]*(?:\.\d+)?'
# 列表式名称取法:head=头行+续行(支付宝);rest=只取续行(头行是「图标+类型+金额」)
NAME_SOURCES = ('head', 'rest')
# 列表式基金名的起点标记(OCR 可能把竖线识成 丨、或整个吃掉)
DEFAULT_NAME_PREFIXES = ('基金|', '基金丨', '基金')
DEFAULT_STRIP_CHARS = ('¥', '￥', '元')
DEFAULT_DATE_PATTERNS = (
    '%Y-%m-%d',
    '%Y/%m/%d',
    '%Y年%m月%d日',
    '%Y-%m-%d %H:%M',
    '%Y/%m/%d %H:%M',
    '%Y-%m-%d %H:%M:%S',
)
# 表头行至少命中这么多列才算表头(避免把数据行误判成表头)
MIN_HEADER_HITS = 2


@dataclass(frozen=True)
class StatementAdapter:
    """一个平台的适配配置(不可变,加载后常驻)。"""

    key: str
    name: str
    mode: str
    source: str
    # 平台标识(交易导入判重的作用域):同一平台的多个适配器必须取同一个值——
    # 支付宝的 PDF/Excel(表格式)与截图(列表式)是两个 key 但同一平台,否则同一笔会被当成两笔。
    # 不配则回落 key(见 _build_adapter)。
    platform: str = ''
    fingerprints: tuple[str, ...] = ()
    header_keywords: tuple[str, ...] = ()
    skip_keywords: tuple[str, ...] = ()
    field_aliases: dict[str, tuple[str, ...]] | None = None
    name_prefixes: tuple[str, ...] = DEFAULT_NAME_PREFIXES
    status_words: tuple[str, ...] = ()
    # 列表式名称取法(见 NAME_SOURCES)
    name_source: str = 'head'
    # 列表式:除方向词外还能「开新块」的词(如「红利再投资」);不配则这类行会被上一条吞掉
    entry_words: tuple[str, ...] = ()
    # 列表式:命中即标记为「暂不支持导入」的词,由校验层跳过并给出提示
    unsupported_words: tuple[str, ...] = ()
    # 分红行(红利再投资 / 现金分红):命中即按「有份额 → 0 成本买入;只有金额 → 金额取负的买入」分流,
    # 不再落进「暂不支持导入」。三平台写法不同(天天「红利再投资」/ 招商「红利再投」/ 蚂蚁「机构分红」),
    # 「红利再投」是「红利再投资」的前缀,一个词覆盖两种写法。
    dividend_words: tuple[str, ...] = ()
    # 列表式:整块文本里同现这些词才算噪音块(如顶部汇总行「买入① 卖出⑨ 定投 分红」)
    skip_when_all_of: tuple[str, ...] = ()
    # 列表式:分组标题(如「2026年07月」)——关闭当前块 + 为无年份日期提供年份,该行本身不入块
    group_headers: tuple[str, ...] = ()
    # 列表式:不带年份的日期格式(如 %m-%d %H:%M:%S),年份取自分组标题
    date_without_year_patterns: tuple[str, ...] = ()
    # 列表式:份额单位(如「份」)——「30.97份」认成份额;不配则只认金额
    share_units: tuple[str, ...] = ()
    strip_chars: tuple[str, ...] = DEFAULT_STRIP_CHARS
    date_patterns: tuple[str, ...] = DEFAULT_DATE_PATTERNS
    tolerance: dict[str, float] | None = None


def project_root() -> Path:
    """项目根目录:向上找含 pyproject.toml 的目录;找不到回退到本文件的上三级(service → 包 → 根)。"""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / 'pyproject.toml').exists():
            return parent
    return here.parents[2]


def _as_str_tuple(raw: Any, *, where: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if raw is None:
        return default
    if isinstance(raw, str):
        return (raw,)
    if not isinstance(raw, (list, tuple)):
        raise ServiceWarning(message=f'平台适配配置 {where} 需要是字符串列表')
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _build_adapter(raw: Any, path: Path) -> StatementAdapter:
    """把一份 YAML 转成适配器;任何缺项/错项都带文件名与字段名报错。"""
    if not isinstance(raw, dict):
        raise ServiceWarning(message=f'平台适配配置 {path.name} 的内容不是键值表(YAML 顶层需要是映射)')

    key = str(raw.get('key') or '').strip()
    if not key:
        raise ServiceWarning(message=f'平台适配配置 {path.name} 缺少必填项 key')
    mode = str(raw.get('mode') or '').strip()
    if mode not in MODES:
        raise ServiceWarning(message=f'平台适配配置 {path.name} 的 mode 只能是 {" 或 ".join(MODES)}(当前: {mode or "空"})')
    # 平台标识会进 remark 并用 LIKE '导入:<platform>:%' 圈作用域,故不许出现 % _ : 这类通配/分隔字符
    platform = str(raw.get('platform') or key).strip()
    if not platform.replace('-', '').replace('_', '').isalnum():
        raise ServiceWarning(
            message=f'平台适配配置 {path.name} 的 platform 只能是中英文/数字/-/_(当前: {platform or "空"})'
        )

    fields_raw = raw.get('fields')
    if not isinstance(fields_raw, dict) or not fields_raw:
        raise ServiceWarning(message=f'平台适配配置 {path.name} 缺少必填项 fields(字段别名表)')
    unknown = [name for name in fields_raw if name not in KNOWN_FIELDS]
    if unknown:
        raise ServiceWarning(
            message=f'平台适配配置 {path.name} 的 fields 里有不认识的字段名 {"、".join(unknown)}；'
            f'可用字段: {"、".join(FIELD_ORDER)}'
        )
    for required in REQUIRED_FIELDS:
        if required not in fields_raw:
            raise ServiceWarning(message=f'平台适配配置 {path.name} 的 fields 缺少必填字段 {required}')
    if not any(name in fields_raw for name in DIRECTION_FIELDS):
        raise ServiceWarning(
            message=f'平台适配配置 {path.name} 的 fields 至少要有一个买卖方向字段（{" / ".join(DIRECTION_FIELDS)}）'
        )

    field_aliases: dict[str, tuple[str, ...]] = {}
    for name in FIELD_ORDER:
        if name not in fields_raw:
            continue
        aliases = _as_str_tuple(fields_raw[name], where=f'{path.name} 的 fields.{name}')
        if not aliases:
            raise ServiceWarning(message=f'平台适配配置 {path.name} 的 fields.{name} 别名列表为空')
        field_aliases[name] = aliases

    name_source = str(raw.get('name_source') or 'head').strip()
    if name_source not in NAME_SOURCES:
        raise ServiceWarning(
            message=f'平台适配配置 {path.name} 的 name_source 只能是 {" 或 ".join(NAME_SOURCES)}(当前: {name_source})'
        )

    clean = raw.get('clean') if isinstance(raw.get('clean'), dict) else {}
    tolerance_raw = raw.get('tolerance') if isinstance(raw.get('tolerance'), dict) else {}
    tolerance: dict[str, float] = {}
    for name, value in tolerance_raw.items():
        try:
            tolerance[str(name)] = float(value)
        except (TypeError, ValueError) as exc:
            raise ServiceWarning(message=f'平台适配配置 {path.name} 的 tolerance.{name} 不是数字') from exc

    return StatementAdapter(
        key=key,
        name=str(raw.get('name') or key).strip(),
        mode=mode,
        source=path.name,
        platform=platform,
        fingerprints=_as_str_tuple(raw.get('fingerprints'), where=f'{path.name} 的 fingerprints'),
        header_keywords=_as_str_tuple(raw.get('header_keywords'), where=f'{path.name} 的 header_keywords'),
        skip_keywords=_as_str_tuple(raw.get('skip_keywords'), where=f'{path.name} 的 skip_keywords'),
        field_aliases=field_aliases,
        name_prefixes=_as_str_tuple(raw.get('name_prefixes'), where=f'{path.name} 的 name_prefixes')
        or DEFAULT_NAME_PREFIXES,
        status_words=_as_str_tuple(raw.get('status_words'), where=f'{path.name} 的 status_words'),
        name_source=name_source,
        entry_words=_as_str_tuple(raw.get('entry_words'), where=f'{path.name} 的 entry_words'),
        unsupported_words=_as_str_tuple(raw.get('unsupported_words'), where=f'{path.name} 的 unsupported_words'),
        dividend_words=_as_str_tuple(raw.get('dividend_words'), where=f'{path.name} 的 dividend_words'),
        skip_when_all_of=_as_str_tuple(raw.get('skip_when_all_of'), where=f'{path.name} 的 skip_when_all_of'),
        group_headers=_as_str_tuple(raw.get('group_headers'), where=f'{path.name} 的 group_headers'),
        date_without_year_patterns=_as_str_tuple(
            clean.get('date_without_year_patterns'), where=f'{path.name} 的 clean.date_without_year_patterns'
        ),
        share_units=_as_str_tuple(raw.get('share_units'), where=f'{path.name} 的 share_units'),
        strip_chars=_as_str_tuple(clean.get('strip_chars'), where=f'{path.name} 的 clean.strip_chars')
        or DEFAULT_STRIP_CHARS,
        date_patterns=_as_str_tuple(clean.get('date_patterns'), where=f'{path.name} 的 clean.date_patterns')
        or DEFAULT_DATE_PATTERNS,
        tolerance=tolerance,
    )


def load_adapters(directory: Path | None = None) -> dict[str, StatementAdapter]:
    """加载目录下的全部 *.yaml;没有配置文件、或任一文件不合法都立即报错(含期望路径)。"""
    base = directory or project_root()
    if not base.is_dir():
        raise ServiceWarning(message=f'平台适配配置目录不存在: {base}')
    files = sorted(base.glob('*.yaml'))
    if not files:
        raise ServiceWarning(
            message=f'项目根目录 {base} 下没有平台适配配置(*.yaml)：至少需要 generic.yaml，'
            f'支付宝/天天基金可分别放 alipay.yaml / tiantian.yaml'
        )

    adapters: dict[str, StatementAdapter] = {}
    for path in files:
        try:
            raw = yaml.safe_load(path.read_text(encoding='utf-8'))
        except Exception as exc:
            raise ServiceWarning(message=f'平台适配配置 {path.name} 不是合法 YAML: {exc}') from exc
        adapter = _build_adapter(raw, path)
        if adapter.key in adapters:
            raise ServiceWarning(
                message=f'平台适配配置 key 重复: {adapter.key}({adapters[adapter.key].source} 与 {path.name})'
            )
        adapters[adapter.key] = adapter
    return adapters


# 启动期加载一次(模块被 controller 间接导入,即路由注册时执行):坏配置当场拦住启动
ADAPTERS: dict[str, StatementAdapter] = load_adapters()
logger.info(f'[导入] 平台适配配置加载完成 count={len(ADAPTERS)} 文件={[item.source for item in ADAPTERS.values()]}')


def get_adapter(key: str) -> StatementAdapter:
    """按 key 取适配器(confirm 用预览回传的 key 解析判重作用域)。

    未知 key 直接报错、不静默降级:平台缺失会让判重失效,把重复记录当新数据累加。
    """
    adapter = ADAPTERS.get(str(key or '').strip())
    if adapter is None:
        raise ServiceWarning(message=f'未知的平台适配器 {key or "空"};可用: {"、".join(sorted(ADAPTERS))}')
    return adapter


def _aliases(adapter: StatementAdapter, field: str) -> tuple[str, ...]:
    return (adapter.field_aliases or {}).get(field, ())


def _map_columns(row: tuple[str, ...], adapter: StatementAdapter) -> dict[str, int]:
    """一行(表头) → {字段: 列号};别名按 YAML 声明顺序优先(前面的别名先命中即定稿)。"""
    columns: dict[str, int] = {}
    for field in FIELD_ORDER:
        for alias in _aliases(adapter, field):
            for idx, cell in enumerate(row):
                if cell and alias in cell:
                    columns[field] = idx
                    break
            if field in columns:
                break
    return columns


def _locate_header(table: DocumentTable, adapter: StatementAdapter) -> tuple[int | None, dict[str, int]]:
    """定位表头行:命中列最多、且命中 header_keywords 者优先;命中不足则视为没有表头。"""
    best_row: int | None = None
    best_columns: dict[str, int] = {}
    best_score = (0, 0)
    for idx, row in enumerate(table.rows):
        columns = _map_columns(row, adapter)
        joined = ' '.join(row)
        keyword_hit = 1 if any(keyword in joined for keyword in adapter.header_keywords) else 0
        score = (len(columns), keyword_hit)
        if score > best_score:
            best_row, best_columns, best_score = idx, columns, score
    if best_row is None or best_score[0] < MIN_HEADER_HITS:
        return None, {}
    return best_row, best_columns


def _clean_value(raw: Any) -> str:
    if raw is None:
        return ''
    return re.sub(r'\s+', ' ', str(raw).replace('\n', ' ').replace('\r', ' ')).strip()


def _parse_number(raw: Any, adapter: StatementAdapter) -> float:
    """金额/份额:去符号与逗号后取第一个数字,取不到按 0(由校验层报问题)。"""
    text = _clean_value(raw)
    for char in adapter.strip_chars:
        text = text.replace(char, '')
    text = text.replace(',', '').replace('，', '')
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group()) if match else 0.0


# 无年份日期只为「判定这一行是不是日期行」时用的占位年份(不产出日期)
_PROBE_YEAR = '2000'


def _date_candidates(text: str) -> list[str]:
    """日期候选写法:整行 / 第一个 token。

    状态词常与日期挤在同一行(「07-01 14:53:38 成功」),整行匹配不了就退到第一个 token
    (「07-01」,或 OCR 吃掉空格后的「11-2414:51:32」)——两种写法得到的是同一天。
    """
    first_token = text.split(' ')[0]
    return [text] if first_token == text else [text, first_token]


def _match_date(raw: Any, adapter: StatementAdapter, year: str | None) -> tuple[bool, str | None]:
    """→ (是不是日期, ISO 日期)。

    先按带年份的格式;再试无年份格式——命中即说明「是日期行」,年份由 year 注入
    (year 为空时只认定为日期行、不产出日期,让校验层报「交易日期无法解析」而不是猜年份)。
    """
    text = _clean_value(raw)
    if not text:
        return False, None

    # 日期格里的「日」可能被空格切开:实测支付宝导出件 1272 格是这个形状(如 '2021/07/2 6 09:33'
    # = 7 月 26 日,同一格还带时间)。**必须先处理它**——否则下面 `_date_candidates` 的首个 token
    # ('2021/07/2')会**成功**解析成 2 日,静默丢掉日的十位(实测 932 行解错、牵出 114 只基金的
    # 残留持仓与「赎回 > 买入」);只有日的首位是 0 时首个 token 才非法、才落到兜底解对。
    compact = re.sub(r'(?<=\d)[ \t]+(?=\d)', '', text)
    if compact != text:
        match = re.search(r'(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})', compact)
        if match:
            matched_year, month, day = match.groups()
            try:
                return True, date(int(matched_year), int(month), int(day)).isoformat()
            except ValueError:
                return True, None  # 是日期但非法(如 2021/13/0 5):交给校验层拦,不猜

    for candidate in _date_candidates(text):
        for pattern in adapter.date_patterns:
            try:
                return True, datetime.strptime(candidate, pattern).date().isoformat()
            except ValueError:
                continue
        for pattern in adapter.date_without_year_patterns:
            try:
                parsed = datetime.strptime(f'{year or _PROBE_YEAR}-{candidate}', f'%Y-{pattern}').date()
            except ValueError:
                continue
            return True, (parsed.isoformat() if year else None)

    # 兜底:被空格切碎的日期(如 '2026/05/0 8')或纯数字串——只有带年份的形态
    compact = re.sub(r'(?<=\d)[ \t]+(?=\d)', '', text)
    match = re.search(r'(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})', compact)
    if not match:
        match = re.search(r'(\d{4})(\d{2})(\d{2})', text)
    if match:
        matched_year, month, day = match.groups()
        try:
            return True, date(int(matched_year), int(month), int(day)).isoformat()
        except ValueError:
            return True, None
    return False, None


def _parse_date(raw: Any, adapter: StatementAdapter, year: str | None = None) -> str | None:
    """日期 → ISO 字符串;无年份格式用 year(来自分组标题)补全。"""
    return _match_date(raw, adapter, year)[1]


def _order_minutes(raw: Any, adapter: StatementAdapter, year: str | None = None) -> int | None:
    """从日期格里取**下单时刻**(当日分钟数);识别不到返回 None。

    时刻只在 pattern 含 `%H` 时才算识别到——'09-01' 与 '09-01 00:00' 必须区分开:
    前者是"没识别到时间"(不能当成 0 点、进而按 15 点前处理),后者是真实时刻。
    表格类文件的日期列是**确认日**(本就无需判 15 点),只有截图/列表式才用得上这个时刻。
    """
    text = _clean_value(raw)
    if not text:
        return None
    for candidate in _date_candidates(text):
        for pattern in adapter.date_patterns:
            if '%H' not in pattern:
                continue
            try:
                parsed = datetime.strptime(candidate, pattern)
            except ValueError:
                continue
            return parsed.hour * 60 + parsed.minute
        if not year:
            continue
        for pattern in adapter.date_without_year_patterns:
            if '%H' not in pattern:
                continue
            try:
                parsed = datetime.strptime(f'{year}-{candidate}', f'%Y-{pattern}')
            except ValueError:
                continue
            return parsed.hour * 60 + parsed.minute
    return None


def _is_date_line(raw: Any, adapter: StatementAdapter) -> bool:
    """只判「这行是不是日期行」:用于把日期行从名称里剔除、以及挑选日期行。"""
    return _match_date(raw, adapter, None)[0]


def _group_header_year(raw: Any, adapter: StatementAdapter) -> str:
    """分组标题(如「2026年07月」)里的年份;不是标题则返回空串。"""
    text = _clean_value(raw)
    if not text:
        return ''
    for pattern in adapter.group_headers:
        try:
            return str(datetime.strptime(text, pattern).year)
        except ValueError:
            continue
    return ''


def _normalize_fund_code(raw: Any) -> str:
    """基金代码:去掉空白,'1' / '1.0' 这类被 Excel 数字化的情况补零到 6 位。"""
    text = _clean_value(raw).replace(' ', '')
    if re.fullmatch(r'\d+(\.0+)?', text):
        return text.split('.')[0].zfill(6)
    return text


def _normalize_order_no(raw: Any) -> str | None:
    text = re.sub(r'\s+', '', _clean_value(raw))
    return text or None


def _has_quantity(raw: Any, adapter: StatementAdapter) -> bool:
    """这一列「真填了数量」:解析出的数值 > 0 才算填了。

    空串与占位符('/' '-' '—' '--'、全角 '／' 等)取不到数字 → 0 → 没填;**'0.00' 同样算没填**
    ——真文件里就有 4 条「用户买入」把申请份额写成 0.00(2026-10 核对:014097 ×2、013577、014748),
    只看「是不是空串/是不是那几个占位符」会把这类行判反。数值口径一条覆盖全部写法,故不再需要
    维护占位符名单(原 buy_when_empty 配置已随之删除)。
    """
    return _parse_number(raw, adapter) > 0


def _resolve_type(values: dict[str, str], adapter: StatementAdapter) -> str | None:
    """判定买卖方向:显式类型列有值就用它,认不出(或压根没映射)再退回「申请了金额还是份额」。

    **卖出词优先**:「定投卖出」这类类型同时含买入词(定投)与卖出词(卖)——买入词只是限定语,
    方向由动词决定;反过来的「卖出买入」不存在,所以先判卖出既安全又唯一正确。
    (2026-09-22 实测:原先先判买入,蚂蚁对账单里的「定投卖出」被判成买入。那两行的申请份额
    是有值的,本来走下面的兜底也能判对赎回,全被这个优先级挡掉了。)

    「认不出」不是判不了——支付宝的「用户跨TA转换」正是靠申请列分转出/转入的
    (2026-09-20 实测:类型列有值但既不含买词也不含卖词时,以前的 return None 会把这类行
    当「买卖方向无法判定」拦掉)。
    """
    type_text = _clean_value(values.get('type', ''))
    if type_text:
        if any(word in type_text for word in SELL_WORDS):
            return 'redemption'
        if any(word in type_text for word in BUY_WORDS):
            return 'purchase'
    return _resolve_type_by_apply_columns(values, adapter)


def _resolve_type_by_apply_columns(values: dict[str, str], adapter: StatementAdapter) -> str | None:
    """类型列认不出时的兜底:看「申请了什么」——申购/转换转入申请的是**金额**,赎回/转换转出申请的是**份额**。

    蚂蚁明细里这两列(申请金额 / 申请份额)**成对且互斥**:一次跨TA转换的两条腿,
    转入腿申请金额有值、申请份额写 '/';转出腿申请金额写 '0.00'、申请份额是真实份额
    (2026-10 核对真文件:26 条跨TA行 = 13 对,每对恰好一买一卖)。两列都映射上时按互斥关系判,
    只映射了一列(或两列同有值——真文件里未出现)就退回单列口径,避免为没见过的形态硬编规则。
    """
    has_amount = 'applyAmount' in values
    has_shares = 'applyShares' in values
    if not has_amount and not has_shares:
        return None
    amount_filled = has_amount and _has_quantity(values.get('applyAmount', ''), adapter)
    shares_filled = has_shares and _has_quantity(values.get('applyShares', ''), adapter)

    if has_amount and has_shares:
        if amount_filled and not shares_filled:
            return 'purchase'
        if shares_filled and not amount_filled:
            return 'redemption'
    # 单列(或两列同有值:沿用「申请份额」这个既有口径)
    if has_shares:
        return 'redemption' if shares_filled else 'purchase'
    return 'purchase' if amount_filled else None


def _build_record(
    values: dict[str, str],
    adapter: StatementAdapter,
    *,
    row: int,
    page_no: int,
    layer: str,
    confidence: float,
    year: str | None = None,
) -> dict:
    """一份原始取值 → 统一的记录字典(字段名与 confirm 契约一致)。"""
    record_type = _resolve_type(values, adapter)
    amount = _parse_number(values.get('amount', ''), adapter)
    shares = _parse_number(values.get('shares', ''), adapter)
    unit_price = _parse_number(values.get('unitPrice', ''), adapter)
    apply_raw = _clean_value(values.get('applyShares', ''))

    # 分红行(红利再投资 / 现金分红 / 蚂蚁的「机构分红」)按**有份额还是有金额**自动分流,
    # 不新增记录类型:份额 > 0 = 红利再投资(0 成本买入,份额涨、钱不动);
    # 只有金额 = 现金分红(0 份额、金额取负 → 冲减持仓成本,钱回到投资者手里)。
    # 放在赎回兜底之前:否则现金分红行(份额 0)会先被「赎回缺份额就用申请份额补」的逻辑吃掉。
    type_text = _clean_value(values.get('type', ''))
    dividend = next((word for word in adapter.dividend_words if word in type_text), '')
    if dividend and (shares > 0 or amount > 0):
        record_type = 'purchase'
        if shares > 0:
            dividend, amount, unit_price = DIVIDEND_REINVEST, 0.0, 0.0
        else:
            dividend, shares, amount, unit_price = DIVIDEND_CASH, 0.0, -amount, 0.0
    else:
        dividend = ''

    # 赎回且确认份额缺失时,用申请份额兜底(支付宝导出常见)
    if record_type == 'redemption' and shares == 0 and amount > 0 and apply_raw:
        shares = _parse_number(apply_raw, adapter)
    if unit_price <= 0 and shares > 0 and amount > 0:
        unit_price = round(amount / shares, 6)

    # 方向不是从类型列认出来的(类型列没映射、或词表认不出)→ 是靠申请份额兜底**猜**的,
    # 校验层据此发一条告警让使用者核对(只有真猜的行才提醒,显式类型的行不打扰)。
    # 分红行不算「猜」:它的方向由上面的分流规则直接定死(红利再投资/现金分红都是买入侧)。
    direction_from_shares = bool(record_type) and not dividend and not any(
        word in type_text for word in (*BUY_WORDS, *SELL_WORDS)
    )

    return {
        'row': row,
        'page': page_no,
        'layer': layer,
        'confidence': confidence,
        'adapter': adapter.key,
        'type': record_type or '',
        # 分红行才有值(红利再投资/现金分红):预览页徽标与落库备注都取它
        'dividend': dividend,
        'fund_code': _normalize_fund_code(values.get('fundCode', '')),
        'fund_name': _clean_value(values.get('fundName', '')),
        'date': _parse_date(values.get('date', ''), adapter, year),
        # 抽取内部字段(预览行是白名单,不会外泄):
        # _date_cell:页边界把日期切成两半时,靠它把尾巴拼回来
        # _direction_from_shares:方向是猜的(见上),校验层据此发告警
        '_date_cell': _clean_value(values.get('date', '')),
        # 下单时刻(截图/列表式才有):确认日要靠它判 15:00 前后,见导入服务的下单切分
        '_order_minutes': _order_minutes(values.get('date', ''), adapter, year),
        '_direction_from_shares': direction_from_shares,
        'amount': amount,
        'shares': shares,
        'unit_price': unit_price,
        'fee': _parse_number(values.get('fee', ''), adapter),
        'order_no': _normalize_order_no(values.get('orderNo', '')),
    }


# 表头规格:(表头行的列数, 字段 → 列号)。多页 PDF 的续页常不重复表头,靠它跨表传递。
HeaderSpec = tuple[int, dict[str, int]]


# 跨页折行续行:页边界会把一条记录的单元格从中间切断,前半留在上一页表末行、后半落到下一页表首行
# (2026-09-20 实测:页末行日期格='2026/03/0'、下一页首行日期格='5 13:45',拼起来才是 '2026/03/05 13:45';
# 名称同理——'招商中证' + '白酒指数 (LOF)A')。续行不带任何独立的交易字段,只带名称尾巴或日期尾巴。
_CONTINUATION_DATE_TAIL = re.compile(r'^\d\s+\d{1,2}:\d{2}$')
# 名称尾巴的长度上限:超过它多半不是折行,只是看着像——宁可不补,也别把两行名字拼成第三个
MAX_CONTINUATION_NAME_LEN = 20


def _is_continuation_row(values: dict[str, str]) -> bool:
    """该行是否只是上一条记录的折行续行。

    判据(2026-09-20 对真实导出件实测:命中 50 条,无一条夹带别的字段):凡「金额/代码/类型/份额/净值/
    手续费」全空、日期列也空或只剩时间尾巴('5 13:45')的行,不可能是独立交易——它只是上一行被页边界
    切断的尾巴。有一项非空就按正常行处理,交给校验层报问题(宁可少补,也不吞掉一条真交易)。
    """
    for field in ('fundCode', 'amount', 'type', 'shares', 'applyShares', 'unitPrice', 'fee'):
        if _clean_value(values.get(field, '')):
            return False
    raw_date = _clean_value(values.get('date', ''))
    return not raw_date or bool(_CONTINUATION_DATE_TAIL.fullmatch(raw_date))


def _absorb_continuation(record: dict, values: dict[str, str], adapter: StatementAdapter) -> None:
    """把续行的名称尾巴 / 日期尾巴并回上一条记录(就地改 record,不产出新记录)。

    - 名称:只往后接(已以该片结尾就不重复接),过长则只丢不接——名称只是展示字段;
    - 日期:原格 + 尾巴拼接后能解析才更新(实测能把 '2026/03/2' 这种**静默解析错**的日期修正回
      '2026-03-25',而不是留一个看着正常的错日期);拼不出就保持原值,仍由校验层拦。
    """
    name = _clean_value(values.get('fundName', ''))
    if name and len(name) <= MAX_CONTINUATION_NAME_LEN and not record['fund_name'].endswith(name):
        record['fund_name'] += name
    tail = _clean_value(values.get('date', ''))
    if tail:
        merged = f'{record.get("_date_cell", "")}{tail}'
        parsed = _parse_date(merged, adapter)
        if parsed:
            record['_date_cell'] = merged
            record['date'] = parsed


def _extract_from_table(
    table: DocumentTable,
    adapter: StatementAdapter,
    header_hint: HeaderSpec | None = None,
    previous: dict | None = None,
) -> tuple[list[dict], HeaderSpec | None]:
    """table 模式:定位表头行 → 按列名映射逐行取字段 → 顺带把本表表头规格交回给调用方。

    本表找不到表头时(多页表格的续页不重复表头),若**首行列数与 header_hint 一致**就沿用它,
    并从第 0 行开始抽;列数不一致一律不继承——宁可少抽,也不能把别的表按交易表的列解析。

    `previous`:上一张表最后一条记录(调用方传入)。页边界会把一条记录的单元格从中间切断,续行落在
    本表表首,只有跨表才能回补(见 `_is_continuation_row` / `_absorb_continuation`)。
    """
    header_row, columns = _locate_header(table, adapter)
    if header_row is not None:
        spec: HeaderSpec = (len(table.rows[header_row]), columns)
        start = header_row + 1
        marker = ' '.join(cell for cell in table.rows[header_row] if cell)
        unsupported = next((word for word in adapter.unsupported_words if word in marker), '')
    elif header_hint is not None and table.rows and len(table.rows[0]) == header_hint[0]:
        spec, columns, start, unsupported = header_hint, header_hint[1], 0, ''
    else:
        return [], None

    records: list[dict] = []
    absorbed = 0
    for idx in range(start, len(table.rows)):
        cells = table.rows[idx]
        ref = table.row_refs[idx] if idx < len(table.row_refs) else idx + 1
        joined = ' '.join(cell for cell in cells if cell)
        if not joined or any(keyword in joined for keyword in adapter.skip_keywords):
            continue
        values = {field: (cells[col] if col < len(cells) else '') for field, col in columns.items()}
        if _is_continuation_row(values):
            target = records[-1] if records else previous
            if target is not None:
                _absorb_continuation(target, values, adapter)
                absorbed += 1
                continue
        record = _build_record(
            values,
            adapter,
            row=ref,
            page_no=table.page_no,
            layer=table.layer,
            confidence=table.confidence,
        )
        # 「跳过并提示」的两种口径:整表级(分红明细表的表头命中,如上表)+ 行级(按**类型列取值**命中,
        # 如支付宝的「机构分红」)。都只打标记,由校验层统一拦下并提示,不落库。
        hit = unsupported or next(
            (word for word in adapter.unsupported_words if word in values.get('type', '')), ''
        )
        if hit:
            record['unsupported'] = hit
        records.append(record)
    if absorbed:
        logger.info(f'[导入] 跨页折行续行回补 条数={absorbed} 页={table.page_no}')
    return records, spec


def _match_labels(line: str, adapter: StatementAdapter) -> list[tuple[str, str]]:
    """一行里可能的「标签: 值」对(按出现位置从左到右切)。"""
    pairs: list[tuple[str, str]] = []
    rest = line
    while rest:
        found: tuple[int, str, str] | None = None
        for field in FIELD_ORDER:
            for alias in _aliases(adapter, field):
                pos = rest.find(alias)
                if pos >= 0 and (found is None or pos < found[0]):
                    found = (pos, field, alias)
        if found is None:
            break
        pos, field, alias = found
        tail = rest[pos + len(alias) :]
        next_pos = len(tail)
        for other_field in FIELD_ORDER:
            for other_alias in _aliases(adapter, other_field):
                other = tail.find(other_alias)
                if 0 <= other < next_pos:
                    next_pos = other
        pairs.append((field, tail[:next_pos].strip(' :：\t')))
        rest = tail[next_pos:]
    return pairs


def _collect_label_blocks(lines: tuple[str, ...], adapter: StatementAdapter) -> list[tuple[int, dict[str, str]]]:
    """labelValue 模式:逐行认标签,键字段重复出现即切下一笔;缺失值可写在下一行。"""
    blocks: list[tuple[int, dict[str, str]]] = []
    current: dict[str, str] = {}
    start = 0
    pending = ''
    for line_no, line in enumerate(lines, start=1):
        pairs = _match_labels(line, adapter)
        if not pairs:
            if pending and line.strip():
                current[pending] = line.strip()
                pending = ''
            continue
        for field, value in pairs:
            if field in RECORD_KEY_FIELDS and current.get(field):
                blocks.append((start, current))
                current = {}
            if not current:
                start = line_no
            if value:
                current[field] = value
                pending = ''
            else:
                pending = field
    if current:
        blocks.append((start, current))
    return [
        (ref, block)
        for ref, block in blocks
        if len(block) >= 2 and (block.get('fundCode') or block.get('date'))
    ]


def _extract_from_lines(document: DocumentContent, adapter: StatementAdapter) -> list[dict]:
    """labelValue 模式:按页逐块取值。"""
    records: list[dict] = []
    for page in document.pages:
        for ref, block in _collect_label_blocks(page.lines, adapter):
            records.append(
                _build_record(
                    block,
                    adapter,
                    row=ref,
                    page_no=page.page_no,
                    layer=page.layer or LAYER_TEXT,
                    confidence=page.confidence,
                )
            )
    return records


def _amount_in_line(line: str) -> str:
    """列表式金额:必须带货币标记(「¥2.00」或「2.00元」),避免把名称里的数字(100ETF)当金额。"""
    match = _AMOUNT_RE.search(line)
    if not match:
        return ''
    return match.group(1) or match.group(2)


def _shares_in_line(line: str, adapter: StatementAdapter) -> str:
    """列表式份额:必须带单位(如「30.97份」)才算,与金额同一原则——不取「第一个数字」。"""
    for unit in adapter.share_units:
        match = re.search(rf'({_NUMBER_TEXT})\s*{re.escape(unit)}', line)
        if match:
            return match.group(1)
    return ''


def _strip_quantities(text: str, adapter: StatementAdapter) -> str:
    """把金额与份额(「52.17元」「30.97份」)从一行里剔掉,只留文字。"""
    text = _AMOUNT_RE.sub('', text)
    for unit in adapter.share_units:
        text = re.sub(rf'{_NUMBER_TEXT}\s*{re.escape(unit)}', '', text)
    return text


def _name_from_block(head: str, rest: list[str], adapter: StatementAdapter) -> str:
    """基金名:按适配器声明的取法(head=头行+续行 / rest=只取续行),剔掉日期行与状态文案。

    支付宝的名称写在头行(「基金|华夏成长混合」),天天基金的头行是「图标 + 类型 + 金额」、
    名称在下一行——所以取法要可配,而不是写死一种。
    """
    if adapter.name_source == 'rest':
        parts: tuple[str, ...] = tuple(rest)
    else:
        for prefix in adapter.name_prefixes:
            pos = head.find(prefix)
            if pos >= 0:
                head = head[pos + len(prefix) :]
                break
        parts = (head, *rest)

    names: list[str] = []
    for index, part in enumerate(parts):
        is_head = adapter.name_source != 'rest' and index == 0
        if not is_head and _is_date_line(part, adapter):  # 日期行不是名称的一部分
            continue
        text = _strip_quantities(part, adapter)
        for word in adapter.status_words:  # 状态文案可能与名称挤在同一行(OCR 折行所致)
            text = text.replace(word, '')
        text = text.strip(' |丨|-')
        if text:
            names.append(text)
    return ''.join(names)


def _values_from_block(lines: list[str], adapter: StatementAdapter, year: str) -> dict[str, str]:
    """一个列表区块 → _build_record 要的字段表(类型/名称/金额/份额/日期)。"""
    head = lines[0]
    # 卖出词在前:头行是「定投卖出」时取到的是「卖」而不是「定投」(与 _resolve_type 同一口径)
    words = (*SELL_WORDS, *BUY_WORDS, *adapter.entry_words)
    return {
        'type': next((word for word in words if word in head), ''),
        'fundName': _name_from_block(head, lines[1:], adapter),
        'amount': next((value for value in (_amount_in_line(line) for line in lines) if value), ''),
        'shares': next((value for value in (_shares_in_line(line, adapter) for line in lines) if value), ''),
        # 日期行整行交给 _build_record:无年份日期要靠分组标题补年份,这里只负责挑出来
        'date': next((line for line in lines if _is_date_line(line, adapter)), ''),
    }


def _split_list_blocks(lines: tuple[str, ...], adapter: StatementAdapter) -> list[tuple[int, list[str], str]]:
    """listItem 模式切块 → [(起始行号, 块内行, 该块生效的年份)]。

    - 方向词(或适配器声明的 entry_words)出现即开新条,不含这些词的后续行归入本条;
    - 分组标题(如「2026年07月」)关闭当前块并记下年份(供无年份日期补全),它自己不入块——
      否则会被上一条吞掉、既污染名称又丢掉年份。
    """
    blocks: list[tuple[int, list[str], str]] = []
    current: list[str] = []
    start = 0
    year = ''
    openers = (*BUY_WORDS, *SELL_WORDS, *adapter.entry_words)
    for line_no, raw in enumerate(lines, start=1):
        text = _clean_value(raw)
        if not text:
            continue
        header_year = _group_header_year(text, adapter)
        if header_year:
            if current:
                blocks.append((start, current, year))
            current, year = [], header_year
            continue
        if any(word in text for word in openers):
            if current:
                blocks.append((start, current, year))
            current, start = [text], line_no
        elif current:
            current.append(text)
    if current:
        blocks.append((start, current, year))
    return blocks


def _extract_from_list(document: DocumentContent, adapter: StatementAdapter) -> list[dict]:
    """listItem 模式:App 交易记录列表截图(无表头,逐条区块,代码由名称解析补)。"""
    records: list[dict] = []
    for page in document.pages:
        for ref, lines, year in _split_list_blocks(page.lines, adapter):
            joined = ' '.join(lines)
            if any(keyword in joined for keyword in adapter.skip_keywords):
                continue
            if adapter.skip_when_all_of and all(word in joined for word in adapter.skip_when_all_of):
                continue
            values = _values_from_block(lines, adapter, year)
            if not values['type'] or not values['fundName']:
                continue
            record = _build_record(
                values,
                adapter,
                row=ref,
                page_no=page.page_no,
                layer=page.layer or LAYER_TEXT,
                confidence=page.confidence,
                year=year,
            )
            # 「红利再投资 / 分红」这类本系统账本表达不了的:照常抽出并带到校验层跳过 + 提示
            unsupported = next((word for word in adapter.unsupported_words if word in values['type']), '')
            if unsupported:
                record['unsupported'] = unsupported
            records.append(record)
    return records


def adapter_score(adapter: StatementAdapter, document: DocumentContent) -> tuple[int, int]:
    """打分 = (平台指纹命中数, 最大表头命中列数);指纹先决定候选,表头命中数只在候选间分高下。"""
    text = '\n'.join(document.lines)
    fingerprint_hits = sum(1 for fingerprint in adapter.fingerprints if fingerprint and fingerprint in text)
    header_hits = 0
    for table in document.tables:
        for row in table.rows:
            header_hits = max(header_hits, len(_map_columns(row, adapter)))
    return fingerprint_hits, header_hits


def detect_adapter(
    document: DocumentContent, adapters: dict[str, StatementAdapter] | None = None
) -> StatementAdapter:
    """选适配器:先看平台指纹,只在「指纹命中的平台」之间用表头命中列数分高下;

    一个平台指纹都没命中时回落 generic(语义兜底)——不按表头命中硬套某个平台,
    避免两个平台别名相近时按文件顺序抛出个随机结果。
    """
    pool = ADAPTERS if adapters is None else adapters
    if not pool:
        raise ServiceWarning(message='平台适配配置为空：项目根目录下至少要有 generic.yaml')

    matched = [
        (adapter, adapter_score(adapter, document))
        for adapter in pool.values()
        if adapter.key != DEFAULT_ADAPTER_KEY
    ]
    matched = [(adapter, score) for adapter, score in matched if score[0] > 0]
    if matched:
        return max(matched, key=lambda item: item[1])[0]

    fallback = pool.get(DEFAULT_ADAPTER_KEY)
    if fallback is None:
        raise ServiceWarning(message=f'没有命中任何平台指纹，且缺少兜底配置 {DEFAULT_ADAPTER_KEY}.yaml')
    return fallback


def extract_records(document: DocumentContent, adapter: StatementAdapter) -> list[dict]:
    """按适配器模式抽取交易记录(纯函数,不落库)。"""
    if adapter.mode == MODE_LABEL_VALUE:
        return _extract_from_lines(document, adapter)
    if adapter.mode == MODE_LIST_ITEM:
        return _extract_from_list(document, adapter)
    records: list[dict] = []
    header_hint: HeaderSpec | None = None
    for table in document.tables:
        # 把上一张表的最后一条记录传进去:页边界切断的续行落在下一张表表首,只有跨表才能回补
        table_records, spec = _extract_from_table(
            table, adapter, header_hint, records[-1] if records else None
        )
        if spec is not None:
            header_hint = spec  # 后续的续页(无表头)沿用最近一张有表头的表的列映射
        records.extend(table_records)
    return records
