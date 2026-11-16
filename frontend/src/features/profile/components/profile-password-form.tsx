// 修改密码表单:原密码 + 新密码 + 确认新密码。
// 提交成功后后端会作废当前会话,hook 里负责清本地登录态并回登录页。
import { zodResolver } from '@hookform/resolvers/zod';
import { motion, useReducedMotion, type Variants } from 'motion/react';
import { useForm } from 'react-hook-form';

import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Spinner } from '@/components/ui/spinner';
import {
  passwordSchema,
  useUpdatePassword,
  type PasswordInput,
} from '@/features/profile/api/profile';

// 与基本资料表单同一套级联节奏
const FORM_CONTAINER: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.06, delayChildren: 0.05 },
  },
};

const FORM_ITEM: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: 'easeOut' },
  },
};

export function ProfilePasswordForm() {
  const updatePassword = useUpdatePassword();
  const reduceMotion = useReducedMotion();
  const form = useForm<PasswordInput>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { oldPassword: '', newPassword: '', confirmPassword: '' },
  });

  return (
    <Form {...form}>
      <motion.form
        onSubmit={form.handleSubmit((values) => updatePassword.mutate(values))}
        className="space-y-4"
        variants={FORM_CONTAINER}
        initial={reduceMotion ? false : 'hidden'}
        animate="visible"
      >
        <motion.div variants={FORM_ITEM}>
          <FormField
            control={form.control}
            name="oldPassword"
            render={({ field }) => (
              <FormItem>
                <FormLabel>原密码</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    autoComplete="current-password"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </motion.div>
        <motion.div variants={FORM_ITEM}>
          <FormField
            control={form.control}
            name="newPassword"
            render={({ field }) => (
              <FormItem>
                <FormLabel>新密码</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    autoComplete="new-password"
                    {...field}
                  />
                </FormControl>
                <FormDescription>至少 5 位</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        </motion.div>
        <motion.div variants={FORM_ITEM}>
          <FormField
            control={form.control}
            name="confirmPassword"
            render={({ field }) => (
              <FormItem>
                <FormLabel>确认新密码</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    autoComplete="new-password"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </motion.div>
        {/* 表单级说明用普通 p:FormDescription 依赖 FormField 的 context,不能裸用 */}
        <motion.p
          className="text-muted-foreground text-[0.8rem]"
          variants={FORM_ITEM}
        >
          修改成功后当前登录会失效,需要用新密码重新登录
        </motion.p>
        <motion.div variants={FORM_ITEM}>
          <Button type="submit" disabled={updatePassword.isPending}>
            {updatePassword.isPending && <Spinner className="size-4" />}
            修改密码
          </Button>
        </motion.div>
      </motion.form>
    </Form>
  );
}
