import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2 } from 'lucide-react';
import { motion, useReducedMotion, type Variants } from 'motion/react';
import { useForm } from 'react-hook-form';
import { Link, useSearchParams } from 'react-router';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import { FieldDescription } from '@/components/ui/field';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { paths } from '@/config/paths';
import { useLogin } from '@/lib/auth';
import { User } from '@/types/api';

import { loginSchema } from '../api/login';

type LoginFormProps = {
  onSuccess?: (user: User) => void;
};

// 表单项依次进场:登录页是进入产品的第一屏,整块级联比一次性出现更有"就绪"感
const FORM_CONTAINER: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.06, delayChildren: 0.1 },
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

export const LoginForm = ({ onSuccess }: LoginFormProps) => {
  const loginMutation = useLogin({
    onSuccess: (user) => {
      if (user) onSuccess?.(user);
    },
  });
  const [searchParams] = useSearchParams();
  const redirectTo = searchParams.get('redirectTo');

  const form = useForm<z.infer<typeof loginSchema>>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });
  const reduceMotion = useReducedMotion();

  return (
    <div>
      <Form {...form}>
        <motion.form
          onSubmit={form.handleSubmit((values) => {
            loginMutation.mutate(values);
          })}
          className="flex flex-col gap-7"
          variants={FORM_CONTAINER}
          initial={reduceMotion ? false : 'hidden'}
          animate="visible"
        >
          <motion.div variants={FORM_ITEM}>
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem className="flex w-full flex-col gap-3">
                  <FormLabel>邮箱</FormLabel>
                  <FormControl>
                    <Input
                      className="h-9 rounded-md px-3"
                      type="email"
                      placeholder="user@example.com"
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
              name="password"
              render={({ field }) => (
                <FormItem className="flex w-full flex-col gap-3">
                  <FormLabel>密码</FormLabel>
                  <FormControl>
                    <Input
                      className="h-9 rounded-md px-3"
                      type="password"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </motion.div>
          <motion.div variants={FORM_ITEM}>
            <Button
              type="submit"
              disabled={loginMutation.isPending}
              className="w-full"
            >
              {loginMutation.isPending && <Loader2 className="animate-spin" />}
              登录
            </Button>
          </motion.div>
          {/* 官方模板:互跳链接在 FieldGroup 流内,与按钮间距同为 gap-7(勿移出 form) */}
          <motion.div variants={FORM_ITEM}>
            <FieldDescription className="text-center">
              没有账号?{' '}
              <Link
                to={paths.auth.register.getHref(redirectTo)}
                className="underline underline-offset-4 hover:text-foreground"
              >
                去注册
              </Link>
            </FieldDescription>
          </motion.div>
        </motion.form>
      </Form>
    </div>
  );
};
