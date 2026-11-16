// src/config/env.ts
import * as z from 'zod';

const createEnv = () => {
  // 1. 定义环境变量 Schema（声明类型 + 校验规则）
  const EnvSchema = z.object({
    API_URL: z.string(),
    ENABLE_API_MOCKING: z
      .string()
      .refine((s) => s === 'true' || s === 'false')
      .transform((s) => s === 'true')
      .optional(),
    APP_URL: z.string().optional().default('http://localhost:3000'),
    APP_MOCK_API_PORT: z.string().optional().default('8080'),
    // ICP 备案号是部署方资产,不随源码公开;部署时通过环境变量注入,为空则登录页不渲染备案链接
    ICP_NO: z.string().optional(),
  });

  // 2. 从 import.meta.env 提取 VITE_APP_ 前缀的变量，剥离前缀
  const envVars = Object.entries(import.meta.env).reduce<
    Record<string, string>
  >((acc, curr) => {
    const [key, value] = curr;
    if (key.startsWith('VITE_APP_')) {
      acc[key.replace('VITE_APP_', '')] = value;
    }
    return acc;
  }, {});

  // 3. 用 Zod 校验
  const parsedEnv = EnvSchema.safeParse(envVars);

  // 4. 校验失败则抛出详细错误
  if (!parsedEnv.success) {
    throw new Error(
      `Invalid env provided.
The following variables are missing or invalid:
${Object.entries(parsedEnv.error.flatten().fieldErrors)
  .map(([k, v]) => `- ${k}: ${v}`)
  .join('\n')}
`,
    );
  }

  return parsedEnv.data;
};

export const env = createEnv();
