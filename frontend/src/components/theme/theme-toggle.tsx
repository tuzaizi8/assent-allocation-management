// src/components/theme/theme-toggle.tsx
import { MoonIcon, SunIcon } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';

import { Button } from '@/components/ui/button';
import { useTheme } from '@/stores/theme-store';

/**
 * 主题切换按钮：light↔dark 切换
 * light 模式显示 MoonIcon（点击切到 dark）
 * dark 模式显示 SunIcon（点击切到 light）
 *
 * 后端类比：相当于后端模板的主题切换按钮，调用 toggle 接口
 */
export function ThemeToggle() {
  const theme = useTheme((s) => s.theme);
  const toggleTheme = useTheme((s) => s.toggleTheme);
  const reduceMotion = useReducedMotion();

  return (
    <Button variant="ghost" size="icon" onClick={toggleTheme}>
      {/* 图标随主题旋转淡换:旧图标先退场,避免日月瞬间硬切 */}
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={theme}
          className="flex"
          initial={
            reduceMotion ? false : { opacity: 0, rotate: -90, scale: 0.8 }
          }
          animate={{ opacity: 1, rotate: 0, scale: 1 }}
          exit={
            reduceMotion
              ? { opacity: 0 }
              : { opacity: 0, rotate: 90, scale: 0.8 }
          }
          transition={{ duration: reduceMotion ? 0 : 0.18, ease: 'easeOut' }}
        >
          {theme === 'light' ? (
            <MoonIcon className="size-4" />
          ) : (
            <SunIcon className="size-4" />
          )}
        </motion.span>
      </AnimatePresence>
    </Button>
  );
}
