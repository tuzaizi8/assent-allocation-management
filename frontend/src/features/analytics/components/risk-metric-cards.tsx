// 关键指标条:13 项指标里取 6 项,窄屏竖排用横线分隔、宽屏两行各 3 个用竖线分隔。
// 不用底色块:浅色主题下 --muted(0.97) 与卡片纯白只差 3% 亮度,分隔感太弱,不如 --border 细线明确。
import { motion, useReducedMotion } from 'motion/react';

import type { MetricItem } from '../lib/metric-items';

import { MetricHelp } from './metric-help';

// 每行 3 个:副文本最长那条(最大回撤的完整起止日期 + 修复天数)约需 270px,3 列才放得下单行
const COLUMNS = 3;

function MetricCard({ item, index }: { item: MetricItem; index: number }) {
  const reduceMotion = useReducedMotion();
  return (
    // testid 供单测定位具体指标取值(与持仓简况页 metric-${label} 同款约定)
    <motion.div
      className="py-3 lg:flex-1 lg:px-4 lg:py-0"
      data-testid={`metric-${item.key}`}
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.35,
        delay: Math.min(index, 6) * 0.05,
        ease: 'easeOut',
      }}
    >
      {/* 指标名用前景色而非灰:6 项一眼扫过时,名字比数值/副文本更需要先被看见 */}
      <div className="text-foreground flex items-center gap-1 text-sm">
        {item.label}
        <MetricHelp helpKey={item.key} />
      </div>
      <div className={`mt-1.5 text-xl font-semibold tabular-nums ${item.tone}`}>
        {item.value}
      </div>
      {item.subtext && (
        <div className="text-muted-foreground mt-1 text-xs">{item.subtext}</div>
      )}
    </motion.div>
  );
}

export function RiskMetricCards({ items }: { items: MetricItem[] }) {
  // 按行切开再交给 flex:若直接给 grid 挂 divide-x,divide-x 会给每行最后一个也加右边框,
  // 行末会凸出一条悬空短线
  const rows: MetricItem[][] = [];
  for (let i = 0; i < items.length; i += COLUMNS) {
    rows.push(items.slice(i, i + COLUMNS));
  }

  return (
    // 内外两层 divide-y 叠起来,窄屏 6 项之间才能连续有横线(不留断口)
    <div className="flex flex-col divide-y divide-border lg:gap-y-6 lg:divide-y-0">
      {rows.map((row, rowIndex) => (
        <div
          key={row[0]?.key}
          className="flex flex-col divide-y divide-border lg:flex-row lg:divide-x lg:divide-y-0"
        >
          {row.map((item, columnIndex) => (
            <MetricCard
              key={item.key}
              item={item}
              index={rowIndex * COLUMNS + columnIndex}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
