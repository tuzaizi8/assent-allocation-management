"""净值/行情新鲜度的窗口划分与缓存 TTL 计算。

每天两个失效点(00:00 与 NAV_REFRESH_DEADLINE_HOUR=22:00):
数据不是今天的、且上次回源尝试早于当前窗口起点 → 过期,本次访问即回源。
akshare 净值发布集中在 17~22 点,22 点做保守判定点——
用户当晚 22 点后首次访问即可见当日净值,白天访问也不会被空转挡住。

判定与写入统一用本地时间(与各处 datetime.now 同一时区基准)。
"""

from datetime import datetime, timedelta

from common.constants import NAV_REFRESH_DEADLINE_HOUR

# 缓存 TTL 下限防抖:窗口切换前最后一刻写入也至少存活一分钟
MIN_CACHE_TTL_SECONDS = 60


def window_start(now: datetime) -> datetime:
    """当前所处窗口的起点:22 点后为今天 22:00,否则今天 0 点。"""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now.hour >= NAV_REFRESH_DEADLINE_HOUR:
        start = start.replace(hour=NAV_REFRESH_DEADLINE_HOUR)
    return start


def window_ttl(now: datetime) -> int:
    """写缓存的 TTL(秒):恰好存活到下一个失效点。

    固定 TTL 会与判定窗口错位——21:59 判新鲜写入的缓存若活 1 小时,
    会把"22 点后可拉新"推迟到 22:59;对齐后 21:59 写入只活约 1 分钟,
    22:00:01 起的首次访问即回源。窗口内缓存即使过期,DB 层判定也是新鲜、
    用同一份数据,TTL 长短不影响行为正确性。
    """
    if now.hour >= NAV_REFRESH_DEADLINE_HOUR:
        next_deadline = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        next_deadline = now.replace(
            hour=NAV_REFRESH_DEADLINE_HOUR, minute=0, second=0, microsecond=0
        )
    return max(int((next_deadline - now).total_seconds()), MIN_CACHE_TTL_SECONDS)
