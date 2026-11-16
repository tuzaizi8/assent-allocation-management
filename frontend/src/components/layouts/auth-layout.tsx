import { motion, useReducedMotion } from 'motion/react';
import * as React from 'react';

import { env } from '@/config/env';
import { cn } from '@/utils/cn';

type AuthLayoutProps = {
  title: string;
  /** 副标题(shadcn 模板语义:登录"欢迎回来" / 注册"创建账户引导"),缺省不显示 */
  description?: string;
  children: React.ReactNode;
  className?: string;
};

// 登录/注册共用布局(2026-10-14 二次改造):照 shadcn login-04/signup-04 区块骨架
// 并按用户要求**镜像**——login-04 原版左表单右图,本项目左图右表单。
// 居中 bg-muted 底上一张双栏 Card:左封面图占位(public/images/auth-cover.svg,
// 换图直接替换该文件;窄屏隐藏),右品牌副标题 + 表单栏(children 由页面传入)。
export const AuthLayout = ({
  title,
  description,
  children,
  className,
}: AuthLayoutProps) => {
  const reduceMotion = useReducedMotion();
  return (
    <div className="bg-muted flex min-h-svh flex-col items-center justify-center p-6 md:p-10">
      <div className="w-full max-w-sm md:max-w-4xl">
        {/* 双栏容器:不用 Card 基础件——项目版 Card 自带 py-(--card-spacing) 内边距,
            会让封面图上下露边不满;自绘同视觉(rounded-xl border bg-card ring)并零内边距 */}
        <motion.div
          className="grid overflow-hidden rounded-xl border bg-card ring-1 ring-foreground/10 md:grid-cols-2"
          initial={reduceMotion ? false : { opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: 'easeOut' }}
        >
          {/* 左:封面视频(即梦 idle 待机循环,ping-pong 无缝;窄屏隐藏,模板同款响应式) */}
          <div className="relative hidden bg-muted md:block">
            <video
              src="/images/auth-idle.mp4?v=4"
              poster="/images/auth-idle-poster.jpg?v=4"
              autoPlay
              muted
              loop
              playsInline
              className="absolute inset-0 h-full w-full object-cover"
            />
          </div>
          {/* 右:标题 + 表单(镜像 login-04:表单在卡片右栏) */}
          <div className="p-6 md:p-8">
            <div className={cn('flex flex-col gap-7', className)}>
              <div className="flex flex-col items-center gap-2 text-center">
                <h1 className="text-2xl font-bold">{title}</h1>
                {description && (
                  <p className="text-muted-foreground text-balance">
                    {description}
                  </p>
                )}
              </div>
              {children}
            </div>
          </div>
        </motion.div>
      </div>
      {/* ICP 备案(工信部要求展示于网站底部;固定钉在视口最底部,新窗口跳转备案系统)
          备案号是部署方资产,由 VITE_APP_ICP_NO 注入,为空则不渲染 */}
      {env.ICP_NO && (
        <a
          href="https://beian.miit.gov.cn/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-muted-foreground hover:text-foreground fixed inset-x-0 bottom-4 z-10 text-center text-xs"
        >
          {env.ICP_NO}
        </a>
      )}
    </div>
  );
};
