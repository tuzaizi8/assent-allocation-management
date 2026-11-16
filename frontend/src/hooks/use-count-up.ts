import { useEffect, useRef, useState } from 'react';

/**
 * 数字滚动:从上次显示值过渡到目标值(easeOutCubic)。
 * 目标为 null 时直接返回 null——缺失值不参与动画,避免把"没有数据"滚成 0。
 * 关闭(enabled=false)或环境没有 requestAnimationFrame 时直接落到目标值,
 * 保证单测与降级路径拿到的是终值而不是中间帧。
 */
export function useCountUp(
  target: number | null,
  { duration = 650, enabled = true } = {},
) {
  const [display, setDisplay] = useState<number | null>(null);
  // 记录上一次真正画到屏幕上的值:目标连续变化时从当前值续上,而不是每次都从 0 重来
  const displayRef = useRef<number | null>(null);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (frameRef.current != null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }

    if (target == null) {
      displayRef.current = null;
      setDisplay(null);
      return;
    }

    if (!enabled || typeof requestAnimationFrame === 'undefined') {
      displayRef.current = target;
      setDisplay(target);
      return;
    }

    const from = displayRef.current ?? 0;
    // 起始时间取首帧 rAF 的时间戳:浏览器里它与 performance.now() 同源,
    // 但测试环境的 rAF 时间戳另有一套时钟,混用会让进度永远差一点到不了终值
    let startedAt: number | null = null;

    const tick = (now: number) => {
      if (startedAt == null) {
        startedAt = now;
      }
      const progress = Math.min((now - startedAt) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const next = from + (target - from) * eased;
      displayRef.current = next;
      setDisplay(next);
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick);
      } else {
        frameRef.current = null;
        displayRef.current = target;
      }
    };

    frameRef.current = requestAnimationFrame(tick);

    return () => {
      if (frameRef.current != null) {
        cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }
    };
  }, [target, duration, enabled]);

  return display;
}
