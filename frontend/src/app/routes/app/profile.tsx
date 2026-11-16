// 个人资料页:左侧分区导航 + 右侧内容区(照 shadcn-fintech settings 页布局)。
// 「基本资料」区含只读账号概览与可编辑表单;「修改密码」区单独一卡,成功后会话作废。
import { KeyRoundIcon, UserIcon, type LucideIcon } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useState } from 'react';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { useProfile, type Profile } from '@/features/profile/api/profile';
import { ProfileInfoForm } from '@/features/profile/components/profile-info-form';
import { ProfilePasswordForm } from '@/features/profile/components/profile-password-form';
import { cn } from '@/utils/cn';
import { formatDate } from '@/utils/format';

type ProfileSection = 'info' | 'password';

const SECTIONS: { id: ProfileSection; label: string; icon: LucideIcon }[] = [
  { id: 'info', label: '基本资料', icon: UserIcon },
  { id: 'password', label: '修改密码', icon: KeyRoundIcon },
];

/** 只读信息行:label 左、值右(与 DetailDrawer 的 DetailField 同观感) */
const InfoRow = ({ label, value }: { label: string; value: string }) => (
  <div className="flex items-center justify-between gap-4 text-sm">
    <span className="text-muted-foreground shrink-0">{label}</span>
    <span className="truncate font-medium">{value}</span>
  </div>
);

/** 账号概览:头像 + 角色 + 只读信息;数据由页面统一取,故这里只负责展示 */
function AccountOverviewCard({ profile }: { profile: Profile }) {
  return (
    <Card className="h-fit">
      <CardHeader>
        <div className="flex items-center gap-3">
          <Avatar className="size-12">
            <AvatarFallback className="text-base">
              {profile.nickName?.trim()?.[0] ?? '?'}
            </AvatarFallback>
          </Avatar>
          <div className="grid gap-1">
            <div className="flex items-center gap-2">
              <CardTitle className="text-base">
                {profile.nickName || profile.userName}
              </CardTitle>
              <Badge
                variant={profile.role === 'ADMIN' ? 'default' : 'secondary'}
              >
                {profile.role === 'ADMIN' ? '管理员' : '普通用户'}
              </Badge>
            </div>
            <CardDescription className="truncate">
              {profile.email}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <Separator />
        {/* 全宽卡片里两列排:一行一条会留下大段空白 */}
        <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
          <InfoRow label="登录账号" value={profile.userName} />
          <InfoRow label="手机号" value={profile.phonenumber || '未填写'} />
          <InfoRow
            label="上次改密"
            value={
              profile.pwdUpdateDate ? formatDate(profile.pwdUpdateDate) : '—'
            }
          />
          <InfoRow
            label="注册时间"
            value={profile.createTime ? formatDate(profile.createTime) : '—'}
          />
          <InfoRow
            label="最后登录"
            value={profile.loginDate ? formatDate(profile.loginDate) : '—'}
          />
        </div>
      </CardContent>
    </Card>
  );
}

/** 首屏骨架:与右侧「概览卡 + 表单卡」同布局,加载完不跳版 */
function ProfileSkeleton() {
  return (
    <div className="flex flex-col gap-4" data-testid="profile-loading">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <Skeleton className="size-12 rounded-full" />
            <div className="grid flex-1 gap-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-3 w-40" />
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-4 w-full" />
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <Skeleton className="h-4 w-20" />
          <Skeleton className="mt-2 h-3 w-56" />
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="flex flex-col gap-2">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

export default function ProfileRoute() {
  const { data: profile, isLoading, isError } = useProfile();
  // 默认落在「基本资料」:与旧版 Tab 默认值一致,概览仍在这一区内
  const [activeSection, setActiveSection] = useState<ProfileSection>('info');
  const reduceMotion = useReducedMotion();

  return (
    <div className="flex flex-1 flex-col gap-4 lg:flex-row lg:gap-6">
      {/* 左侧分区导航(桌面) */}
      <nav
        aria-label="个人资料分区"
        className="hidden w-52 shrink-0 flex-col gap-1 lg:flex"
      >
        {SECTIONS.map((section) => (
          <Button
            key={section.id}
            variant={activeSection === section.id ? 'secondary' : 'ghost'}
            size="sm"
            className={cn(
              'justify-start gap-2',
              activeSection === section.id && 'font-semibold',
            )}
            onClick={() => setActiveSection(section.id)}
          >
            <section.icon className="size-4" />
            {section.label}
          </Button>
        ))}
      </nav>

      {/* 移动端横向分区条:窄屏没有左侧栏,保持同样的切换入口 */}
      <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-2 lg:hidden">
        {SECTIONS.map((section) => (
          <Button
            key={section.id}
            variant={activeSection === section.id ? 'secondary' : 'ghost'}
            size="sm"
            className="shrink-0 gap-1.5 text-xs"
            onClick={() => setActiveSection(section.id)}
          >
            <section.icon className="size-3.5" />
            {section.label}
          </Button>
        ))}
      </div>

      {/* 右侧内容区:数据未就绪时统一骨架/错误卡,就绪后按分区渲染 */}
      <div className="min-w-0 flex-1">
        {isLoading ? (
          <ProfileSkeleton />
        ) : isError || !profile ? (
          <Card>
            <CardContent className="text-destructive py-10 text-center text-sm">
              资料加载失败,请刷新重试
            </CardContent>
          </Card>
        ) : (
          // 切分区时旧内容先退场、新内容再进场,避免两套表单在布局里重叠
          <AnimatePresence mode="wait">
            <motion.div
              key={activeSection}
              initial={reduceMotion ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -8 }}
              transition={{
                duration: reduceMotion ? 0 : 0.2,
                ease: 'easeOut',
              }}
            >
              {activeSection === 'info' ? (
                <div className="flex flex-col gap-4">
                  <AccountOverviewCard profile={profile} />
                  <Card>
                    <CardHeader>
                      <CardTitle>基本资料</CardTitle>
                      <CardDescription>
                        修改昵称与手机号,邮箱为登录账号不可改
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <ProfileInfoForm profile={profile} />
                    </CardContent>
                  </Card>
                </div>
              ) : (
                <Card>
                  <CardHeader>
                    <CardTitle>修改密码</CardTitle>
                    <CardDescription>
                      修改成功后当前登录会失效,需要用新密码重新登录
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ProfilePasswordForm />
                  </CardContent>
                </Card>
              )}
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}
