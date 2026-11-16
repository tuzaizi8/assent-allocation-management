// 指标标题后的「空心圆感叹号」+ 悬浮讲解卡。
// 讲解文案按 key 取自 lib/metric-glossary,本组件只管呈现。
import { CircleAlertIcon } from 'lucide-react';

import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from '@/components/ui/hover-card';

import { METRIC_GLOSSARY } from '../lib/metric-glossary';

export function MetricHelp({ helpKey }: { helpKey: string }) {
  const entry = METRIC_GLOSSARY[helpKey];
  // 讲解是纯增益信息:缺一条也不该让整个页面炸掉
  if (!entry) return null;
  return (
    // openDelay 默认 700ms 会让人以为没反应,200ms 既不用刻意停留也不易误触
    <HoverCard openDelay={200}>
      <HoverCardTrigger asChild>
        {/* 做成 button 而非裸图标:能进 Tab 序列,aria-label 也让读屏有交代 */}
        <button
          type="button"
          aria-label={`${entry.title}是什么意思`}
          className="text-muted-foreground hover:text-foreground focus-visible:text-foreground shrink-0 cursor-help"
        >
          <CircleAlertIcon className="size-3.5" />
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="w-72">
        <div className="font-medium">{entry.title}</div>
        <p className="text-muted-foreground mt-1 text-xs">{entry.what}</p>
        <p className="text-muted-foreground mt-1 text-xs">{entry.use}</p>
      </HoverCardContent>
    </HoverCard>
  );
}
