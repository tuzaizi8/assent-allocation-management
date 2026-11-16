import { motion, useReducedMotion } from 'motion/react';

import { cn } from '@/utils/cn';

/** 柱状骨架的参数:高度做成有起伏的四个柱,避免空态插画看起来像加载占位 */
const BARS = [
  { x: 18, height: 18 },
  { x: 34, height: 28 },
  { x: 50, height: 14 },
  { x: 66, height: 24 },
];

const BASELINE = 38;

/**
 * 表格空态的轻量插画:四根柱子依次长高 + 一个圆点弹入。
 * 尺寸与文案由消费方控制(表格里只当一条 44px 高的装饰),不抢「暂无数据」的注意力。
 */
export function EmptyStateArt({ className }: { className?: string }) {
  const reduceMotion = useReducedMotion();

  return (
    // 纯装饰:空态文案已由旁边文字播报,避免读屏重复念一遍
    <svg
      viewBox="0 0 84 44"
      aria-hidden="true"
      className={cn('h-11 w-20', className)}
    >
      <line
        x1="8"
        y1={BASELINE}
        x2="76"
        y2={BASELINE}
        stroke="var(--border)"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      {BARS.map((bar, index) => (
        <motion.rect
          key={bar.x}
          x={bar.x}
          width="8"
          rx="2"
          fill="var(--primary)"
          fillOpacity={0.2}
          initial={
            reduceMotion ? false : { height: 0, y: BASELINE, opacity: 0 }
          }
          animate={{ height: bar.height, y: BASELINE - bar.height, opacity: 1 }}
          transition={{
            duration: 0.45,
            delay: 0.05 + index * 0.08,
            ease: 'easeOut',
          }}
        />
      ))}
      <motion.circle
        cx="74"
        cy="16"
        r="3"
        fill="var(--primary)"
        fillOpacity={0.4}
        initial={reduceMotion ? false : { scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.4, type: 'spring', stiffness: 300, damping: 20 }}
      />
    </svg>
  );
}
