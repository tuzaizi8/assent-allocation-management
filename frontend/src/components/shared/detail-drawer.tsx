// src/components/shared/detail-drawer.tsx —— 详情抽屉骨架 + 字段行
// users/logs 两页逐字重复的详情抽屉统一收口;视觉与交互结果与页内实现一致
// 只收骨架(Drawer + 头部 + 字段网格容器 + 底部关闭),字段内容由各页以 children 声明:
// logs 有 JSON <pre> 等宽块与 errorMsg 条件全宽块,做成声明式 fields 配置会让共享层堆满逃生口
// scroll 开关而非统一:users 的网格无滚动,logs 必须滚动——抽屉限高 80vh,
// 长 JSON 不滚会撑破高度被截断;若统一给 users 加上 flex-1 会无谓拉伸,属行为变更
import type * as React from 'react';

import { Button } from '@/components/ui/button';
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/utils/cn';

export type DetailDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  /** 详情按需查询中(logs 大字段单查;users 直接用行数据,不传) */
  loading?: boolean;
  /** 字段网格是否可滚动(logs 长 JSON 传 true) */
  scroll?: boolean;
  children: React.ReactNode;
};

export function DetailDrawer({
  open,
  onOpenChange,
  title,
  description,
  loading = false,
  scroll = false,
  children,
}: DetailDrawerProps) {
  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>{title}</DrawerTitle>
          <DrawerDescription>{description}</DrawerDescription>
        </DrawerHeader>
        {loading && (
          // 骨架按字段行铺:与真实详情同样的两列网格,加载完不跳版
          <div className="grid grid-cols-2 gap-4 px-4 pb-4">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="flex flex-col gap-1">
                <Skeleton className="h-3 w-12" />
                <Skeleton className="h-4 w-full" />
              </div>
            ))}
            <Spinner className="sr-only" />
          </div>
        )}
        {/* flex-1 + min-h-0:抽屉限高 80vh 内的滚动区(否则长 JSON 撑破高度被截断) */}
        <div
          key={loading ? 'loading' : 'ready'}
          className={cn(
            'animate-in fade-in-0 grid grid-cols-2 gap-4 px-4 pb-4 text-sm duration-150 motion-reduce:animate-none',
            scroll && 'min-h-0 flex-1 overflow-y-auto',
          )}
        >
          {children}
        </div>
        <DrawerFooter>
          <DrawerClose asChild>
            <Button variant="outline">关闭</Button>
          </DrawerClose>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  );
}

// 字段行:label + value 上下排布。原为 logs 页本地组件,users 页手写过 7 次同构结构
// value 收 ReactNode:users 的状态字段要渲染 StatusBadge,不能限死 string
// break-all 沿用 logs 版:抽屉窄栏里超长字段值应换行而非溢出(users 的邮箱/手机号不会触发,无视觉回归)
export function DetailField({
  label,
  value,
}: {
  label: string;
  value?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-muted-foreground">{label}</span>
      <span className="break-all">{value ?? '-'}</span>
    </div>
  );
}
