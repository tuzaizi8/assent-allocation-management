// statement-import-state 的单测,核心是「跨挂载存活」:
// 导入请求没结束前,把组件卸载(等价于切到别的菜单)再重新挂载,仍必须处于占用期。
// 这正是 2026-09-21 使用者报的 bug:切页回来进度提示消失、选择文件又能点了,而请求其实还在后台跑。
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

import {
  useConfirmStatementImport,
  useStatementImportState,
  type StatementConfirmPayload,
  type StatementConfirmResult,
} from '@/features/statement-import/api/statement-import';
import { api } from '@/lib/api-client';

vi.mock('@/lib/api-client', () => ({ api: { post: vi.fn() } }));
// 回执 toast 与本用例无关,挡掉以免依赖 sonner 的渲染环境
vi.mock('sonner', () => ({ toast: { success: vi.fn(), warning: vi.fn() } }));

const post = vi.mocked(api.post);

const SUCCESS_RESULT = {
  success: true,
  imported: { purchases: 2, redemptions: 1, skipped: 0 },
  positionsCreated: 2,
  errors: [],
} as StatementConfirmResult;

const PAYLOAD: StatementConfirmPayload = {
  adapter: 'alipay',
  fileName: 'alipay-2026.pdf',
  records: [
    {
      fundCode: '000001',
      fundName: '华夏成长混合',
      date: '2026-05-08',
      type: '买入',
      amount: 100,
      shares: 80,
      unitPrice: 1.25,
      fee: 0,
      orderNo: null,
    },
    {
      fundCode: '110011',
      fundName: '易方达中小盘',
      date: '2026-05-09',
      type: '买入',
      amount: 200,
      shares: 100,
      unitPrice: 2,
      fee: 0,
      orderNo: null,
    },
  ],
};

/** 手动控制的 promise:用来把"请求进行中"这一刻固定住 */
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

/** 每个用例一个独立 QueryClient(同一 wrapper 内共享,跨挂载也是同一个) */
const makeWrapper = () => {
  const queryClient = new QueryClient();
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

test('还没导过:既不占用也没有回执', () => {
  const { result } = renderHook(() => useStatementImportState(), {
    wrapper: makeWrapper(),
  });

  expect(result.current).toMatchObject({
    importing: false,
    result: null,
    recordCount: 0,
  });
});

test('切页卸载再回来:请求没结束就仍处于占用期', async () => {
  const pending = deferred<StatementConfirmResult>();
  post.mockReturnValue(pending.promise);
  const wrapper = makeWrapper();

  const { result: mutator, unmount: unmountMutator } = renderHook(
    () => useConfirmStatementImport(),
    { wrapper },
  );
  act(() => mutator.current.mutate(PAYLOAD));

  const { result: before, unmount: unmountPage } = renderHook(
    () => useStatementImportState(),
    { wrapper },
  );
  await waitFor(() => expect(before.current.importing).toBe(true));

  // 模拟"切到别的菜单":发起方与展示方一起卸载(请求不会被取消)
  unmountPage();
  unmountMutator();

  const { result: after } = renderHook(() => useStatementImportState(), {
    wrapper,
  });
  expect(after.current.importing).toBe(true);
  // 文件名与条数来自 mutation 变量 → 切页回来仍显示得出来
  expect(after.current.fileName).toBe('alipay-2026.pdf');
  expect(after.current.recordCount).toBe(2);
});

test('离开期间跑完:切回来能看到完成回执', async () => {
  const pending = deferred<StatementConfirmResult>();
  post.mockReturnValue(pending.promise);
  const wrapper = makeWrapper();

  const { result: mutator, unmount: unmountMutator } = renderHook(
    () => useConfirmStatementImport(),
    { wrapper },
  );
  act(() => mutator.current.mutate(PAYLOAD));

  const { result: before, unmount: unmountPage } = renderHook(
    () => useStatementImportState(),
    { wrapper },
  );
  await waitFor(() => expect(before.current.importing).toBe(true));

  unmountPage();
  unmountMutator();
  await act(async () => {
    pending.resolve(SUCCESS_RESULT);
  });

  const { result: after } = renderHook(() => useStatementImportState(), {
    wrapper,
  });
  await waitFor(() => expect(after.current.importing).toBe(false));
  expect(after.current.result).toEqual(SUCCESS_RESULT);
});

test('失败:占用期结束且没有回执(不会永久锁死页面)', async () => {
  post.mockRejectedValue(new Error('boom'));
  const wrapper = makeWrapper();

  const { result: mutator } = renderHook(() => useConfirmStatementImport(), {
    wrapper,
  });
  act(() => mutator.current.mutate(PAYLOAD));

  const { result } = renderHook(() => useStatementImportState(), { wrapper });
  await waitFor(() => expect(result.current.importing).toBe(false));
  expect(result.current.result).toBeNull();
});
