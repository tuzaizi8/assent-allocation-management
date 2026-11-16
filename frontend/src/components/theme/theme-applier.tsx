// src/components/theme/theme-applier.tsx
import { useEffect } from 'react';

import { useTheme } from '@/stores/theme-store';

/**
 * 主题应用器：监听 theme 变化，切换 document.documentElement 的 dark class
 * 放 provider.tsx 顶层，全局生效（登录页也支持主题）
 *
 * 后端类比：相当于后端中间件，在每个请求前设置全局模板变量（如 theme）
 */
export function ThemeApplier() {
  const theme = useTheme((s) => s.theme);

  useEffect(() => {
    // 切换 dark class（Tailwind darkMode: 'class' 生效）
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  return null; // 不渲染 UI，只做副作用
}
