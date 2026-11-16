import { Badge } from '@/components/ui/badge';
import { cn } from '@/utils/cn';

type FundTypeTone =
  'emerald' | 'sky' | 'amber' | 'violet' | 'teal' | 'rose' | 'indigo' | 'muted';

/** 彩色 chip 的浅底样式(与 Badge 的 outline 组合使用) */
const TONE_BADGE: Record<FundTypeTone, string> = {
  emerald:
    'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-400',
  sky: 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-400',
  amber:
    'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-400',
  violet:
    'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-400',
  teal: 'border-teal-200 bg-teal-50 text-teal-700 dark:border-teal-800 dark:bg-teal-950/40 dark:text-teal-400',
  rose: 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-400',
  indigo:
    'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-400',
  muted: 'text-muted-foreground',
};

/** 主列首字方块的同色系底色(比 chip 实一档,28px 方块才看得清) */
const TONE_BLOCK: Record<FundTypeTone, string> = {
  emerald:
    'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400',
  sky: 'bg-sky-100 text-sky-700 dark:bg-sky-950/50 dark:text-sky-400',
  amber: 'bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-400',
  violet:
    'bg-violet-100 text-violet-700 dark:bg-violet-950/50 dark:text-violet-400',
  teal: 'bg-teal-100 text-teal-700 dark:bg-teal-950/50 dark:text-teal-400',
  rose: 'bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-400',
  indigo:
    'bg-indigo-100 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-400',
  muted: '',
};

/**
 * 类型串 → 首字 + 色调。
 * 顺序有意义:「指数型-股票」要先命中「指数」,否则会被「股票」抢走;债券/混合同理。
 */
const FUND_TYPE_RULES: { match: string; char: string; tone: FundTypeTone }[] = [
  { match: 'QDII', char: 'Q', tone: 'rose' },
  { match: 'FOF', char: 'F', tone: 'indigo' },
  { match: '债券', char: '债', tone: 'amber' },
  { match: '指数', char: '指', tone: 'violet' },
  { match: '混合', char: '混', tone: 'sky' },
  { match: '股票', char: '股', tone: 'emerald' },
  { match: '货币', char: '货', tone: 'teal' },
];

export type FundTypeVisual = {
  char: string;
  badgeClass: string;
  blockClass: string;
};

/** 基金类型 → 首字与配色;类型为空返回 null,未知类型用首字 + 中性色兜底 */
export function getFundTypeVisual(type?: string | null): FundTypeVisual | null {
  if (!type) return null;
  const upper = type.toUpperCase();
  const rule = FUND_TYPE_RULES.find((item) =>
    /^[A-Z]/.test(item.match)
      ? upper.includes(item.match)
      : type.includes(item.match),
  );
  const tone = rule?.tone ?? 'muted';
  return {
    char: rule?.char ?? type.slice(0, 1),
    badgeClass: TONE_BADGE[tone],
    blockClass: TONE_BLOCK[tone],
  };
}

export function FundTypeBadge({
  type,
  className,
}: {
  type?: string | null;
  className?: string;
}) {
  const visual = getFundTypeVisual(type);
  if (!type || !visual) {
    return <span className="text-muted-foreground">-</span>;
  }
  return (
    <Badge
      variant="outline"
      className={cn('px-1.5', visual.badgeClass, className)}
    >
      {type}
    </Badge>
  );
}
