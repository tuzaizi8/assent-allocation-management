import {
  DefaultOptions,
  MutationCache,
  QueryClient,
  UseMutationOptions,
} from '@tanstack/react-query';
import { toast } from 'sonner';

export const queryConfig = {
  queries: {
    // throwOnError: true,
    refetchOnWindowFocus: false, // 切回标签页不自动重拉
    retry: false, // 失败不重试（业务错误码由拦截器统一提示）
    staleTime: 1000 * 60, // 数据 1 分钟内视为新鲜，不重拉
  },
} satisfies DefaultOptions;

/**
 * QueryClient 工厂(2026-09-01 成功通知轮):provider 与 test-utils 共用。
 *
 * MutationCache.onSuccess 全局成功钩子——写操作成功统一弹 toast:
 * - 失败侧早已由 api-client 拦截器统一弹(错误 toast),成功侧此前静默
 * - 文案来自后端响应体 msg(各 service 统一"新增成功/更新成功/删除成功")
 * - mutation 配 meta: { silentSuccess: true } 跳过(如登录——页面有自己的跳转/提示)
 * - 新增 mutation 自动纳入,无需逐个 onSuccess(此前 21 个 mutation 全静默的根因即无全局机制)
 */
export const createQueryClient = () =>
  new QueryClient({
    defaultOptions: queryConfig,
    mutationCache: new MutationCache({
      onSuccess: (data, _variables, _context, mutation) => {
        if (mutation.options.meta?.silentSuccess) return;
        const msg = (data as any)?.msg as string | undefined;
        if (msg) toast.success(msg);
      },
    }),
  });

export type ApiFnReturnType<FnType extends (...args: any) => Promise<any>> =
  Awaited<ReturnType<FnType>>;

export type QueryConfig<T extends (...args: any[]) => any> = Omit<
  ReturnType<T>,
  'queryKey' | 'queryFn'
>;

export type MutationConfig<
  MutationFnType extends (...args: any) => Promise<any>,
> = UseMutationOptions<
  ApiFnReturnType<MutationFnType>,
  Error,
  Parameters<MutationFnType>[0]
>;
