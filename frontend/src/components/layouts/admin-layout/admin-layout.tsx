// src/components/layouts/admin-layout/admin-layout.tsx
import { motion, useReducedMotion } from 'motion/react';
import { Fragment, type ReactNode } from 'react';
import { Outlet, useLocation, useMatches } from 'react-router';

import { ThemeToggle } from '@/components/theme/theme-toggle';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Separator } from '@/components/ui/separator';
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from '@/components/ui/sidebar';

/**
 * 后台管理布局(sidebar-08 官方方案):
 *   SidebarProvider > [AppSidebar(props 注入)] + SidebarInset > SiteHeader + Outlet
 * 折叠态/移动端 Sheet/Cmd+B 快捷键由 SidebarProvider 内建(原 menu-store 消亡)
 *
 * 架构说明:sidebar 通过 props 注入(由 app 层传入 AppSidebar),
 * 避免共享层 components 直接依赖 features 层(ESLint import/no-restricted-paths)
 */
export function AdminLayout({ sidebar }: { sidebar: ReactNode }) {
  const location = useLocation();
  const reduceMotion = useReducedMotion();
  return (
    <SidebarProvider>
      {sidebar}
      {/* 右侧主区(官方 inset 变体:md 起自带 m-2 + rounded-xl + shadow-sm)。
          shadow-sm 在纯白主区上几乎看不出抬升,这里叠加一层柔和投影把它"浮"起来。
          带 ! 是刻意的:官方那层是 `md:peer-data-[variant=inset]:shadow-sm`,变体选择器
          比同类 shadow 工具类优先级更高,不加 ! 时谁生效取决于 CSS 顺序,不可靠。
          参数的两条边界:① 模糊≤10px——再大就会在主区四周糊出一圈黑带(硬朗且脏);
          ② 扩散必须为 0 不能取负——主区四周只有 8px 空隙(m-2),负扩散会把投影矩形缩到
          面板底下被自己挡住,等于没有阴影(实测 -4px/+0.08 时完全看不见)。
          深色底上黑影不可见,故 dark 变体另给更高不透明度 */}
      {/* bg-[var(--content-bg)] 覆盖官方的 bg-background:卡片是纯白,底板用米白才浮得出来 */}
      <SidebarInset className="bg-[var(--content-bg)] md:shadow-[0_2px_4px_rgb(0_0_0/0.06),0_4px_10px_rgb(0_0_0/0.12)]! dark:md:shadow-[0_2px_4px_rgb(0_0_0/0.35),0_4px_10px_rgb(0_0_0/0.45)]!">
        <SiteHeader />
        <div className="flex flex-1 flex-col gap-4 p-4 pt-0">
          {/* 路由切换时整页轻量淡入:只动 opacity + 4px,不做退出等待,避免与懒加载/请求竞态 */}
          <motion.div
            key={location.pathname}
            className="flex flex-1 flex-col"
            initial={reduceMotion ? false : { opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            <Outlet />
          </motion.div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}

/**
 * 站点顶栏(sidebar-08 官方结构):Trigger + 分隔线 + 面包屑
 * 面包屑动态化:基于路由层级链(useMatches + handle.title 约定),
 * 最后一项渲染为 BreadcrumbPage(当前页),其余为普通项
 */
function SiteHeader() {
  const matches = useMatches();
  const crumbs = matches.filter(
    (m) =>
      (m.handle as { title?: string } | undefined)?.title && m.pathname !== '/',
  );

  return (
    <header className="flex h-16 shrink-0 items-center gap-2">
      <div className="flex items-center gap-2 px-4">
        <SidebarTrigger className="-ml-1" />
        <Separator
          orientation="vertical"
          className="mr-2 data-[orientation=vertical]:h-4"
        />
        {crumbs.length > 0 && (
          <Breadcrumb>
            <BreadcrumbList>
              {crumbs.map((m, i) => {
                const handle = m.handle as { title: string; parent?: string };
                return (
                  <Fragment key={m.id}>
                    {/* 父级项(官方 sidebar-08 结构):BreadcrumbLink 纯展示——
                        菜单 M 目录不可导航(与 NavMain 目录行为一致),不引入死链接;
                        父级与当前页之间渲染 separator(官方结构) */}
                    {handle.parent && (
                      <>
                        {i > 0 && (
                          <BreadcrumbSeparator className="hidden md:block" />
                        )}
                        <BreadcrumbItem className="hidden md:block">
                          <BreadcrumbLink>{handle.parent}</BreadcrumbLink>
                        </BreadcrumbItem>
                        <BreadcrumbSeparator className="hidden md:block" />
                      </>
                    )}
                    {i > 0 && !handle.parent && (
                      <BreadcrumbSeparator className="hidden md:block" />
                    )}
                    {/* 当前页:不加 hidden(官方行为——移动端仍显示当前页) */}
                    <BreadcrumbItem>
                      <BreadcrumbPage>{handle.title}</BreadcrumbPage>
                    </BreadcrumbItem>
                  </Fragment>
                );
              })}
            </BreadcrumbList>
          </Breadcrumb>
        )}
      </div>
      {/* 右侧业务保留:主题切换(NavUser 已承载用户菜单) */}
      <div className="ml-auto pr-4">
        <ThemeToggle />
      </div>
    </header>
  );
}
