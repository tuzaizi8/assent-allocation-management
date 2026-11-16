import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

type ThemeStore = {
  theme: 'light' | 'dark';
  setTheme: (theme: 'light' | 'dark') => void;
  toggleTheme: () => void; // 13.5 新增：便捷切换方法
};

export const useTheme = create<ThemeStore>()(
  persist(
    (set) => ({
      theme: 'light',
      setTheme: (theme) => set({ theme }),
      // 13.5 新增：无参切换，自动 light↔dark
      toggleTheme: () =>
        set((s) => ({ theme: s.theme === 'light' ? 'dark' : 'light' })),
    }),
    {
      name: 'app-theme', // localStorage key
      storage: createJSONStorage(() => localStorage), // 存储引擎
    },
  ),
);
