// 基本资料表单:昵称与手机号可改,邮箱只读(注册时 user_name = email,改了等于换登录账号)
import { zodResolver } from '@hookform/resolvers/zod';
import { motion, useReducedMotion, type Variants } from 'motion/react';
import { useForm } from 'react-hook-form';

import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Spinner } from '@/components/ui/spinner';
import {
  profileSchema,
  useUpdateProfile,
  type Profile,
  type ProfileInput,
} from '@/features/profile/api/profile';

// 字段依次进场:与登录/注册表单同一节奏,切换分区后表单不会整块硬出现
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

export function ProfileInfoForm({ profile }: { profile: Profile }) {
  const updateProfile = useUpdateProfile();
  const reduceMotion = useReducedMotion();
  const form = useForm<ProfileInput>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      nickName: profile.nickName ?? '',
      phonenumber: profile.phonenumber ?? '',
    },
  });

  return (
    <Form {...form}>
      <motion.form
        onSubmit={form.handleSubmit((values) => updateProfile.mutate(values))}
        className="space-y-4"
        variants={FORM_CONTAINER}
        initial={reduceMotion ? false : 'hidden'}
        animate="visible"
      >
        <motion.div variants={FORM_ITEM}>
          <FormField
            control={form.control}
            name="nickName"
            render={({ field }) => (
              <FormItem>
                <FormLabel>昵称</FormLabel>
                <FormControl>
                  <Input maxLength={30} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </motion.div>
        <motion.div variants={FORM_ITEM}>
          <FormField
            control={form.control}
            name="phonenumber"
            render={({ field }) => (
              <FormItem>
                <FormLabel>手机号</FormLabel>
                <FormControl>
                  <Input
                    inputMode="numeric"
                    maxLength={11}
                    placeholder="选填"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </motion.div>
        {/* 邮箱不参与表单:它不是可提交字段,用 disabled Input 明示"只读" */}
        <motion.div variants={FORM_ITEM} className="space-y-2">
          <Label htmlFor="profile-email">邮箱</Label>
          <Input id="profile-email" value={profile.email ?? ''} disabled />
          <p className="text-muted-foreground text-[0.8rem]">
            邮箱是登录账号,暂不支持修改
          </p>
        </motion.div>
        <motion.div variants={FORM_ITEM}>
          <Button type="submit" disabled={updateProfile.isPending}>
            {updateProfile.isPending && <Spinner className="size-4" />}
            保存修改
          </Button>
        </motion.div>
      </motion.form>
    </Form>
  );
}
