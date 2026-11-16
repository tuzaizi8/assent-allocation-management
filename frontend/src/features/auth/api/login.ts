import { z } from 'zod';

// === Zod schema ===

export const loginSchema = z.object({
  email: z.string().email('请输入有效邮箱'),
  password: z.string().min(8, '密码至少 8 位'),
});

export type LoginValues = z.infer<typeof loginSchema>;
