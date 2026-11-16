// api-client.ts 错误分流单测——通过 mock axios adapter 模拟后端各种错误响应,
// 对拦截器整体行为(错误拦截器 → handleHttpError)做黑盒断言。
// 锁定的关键新分支:422 detail 拼接 / ERR_CANCELED 静默 / 503 文案 / 401 跳登录。
import { AxiosError, CanceledError } from 'axios';
// mock sonner:拦截器内部直接调用 toast,组件外无法用 renderToPipeableStream 等方式观察
// (vi.mock 会被 vitest hoist到文件顶部,即使 import 在 mock 之后也生效)
import { toast } from 'sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AUTH_FLASH_KEY, api } from '../api-client';

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    warning: vi.fn(),
    success: vi.fn(),
  },
}));

/** 短路 adapter:不真发请求,直接按测试注入的响应/错误返回 */
function mockAdapter(handler: () => never) {
  api.defaults.adapter = handler as any;
}

/** 构造一个已被取消的请求(React Query 卸载场景的真实形态) */
function canceledError() {
  return new CanceledError('canceled');
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('api-client 错误分流', () => {
  it('422 校验错误:解析 FastAPI detail 拼成「字段: msg」可读文案', async () => {
    mockAdapter(() => {
      throw Object.assign(new AxiosError('Request failed'), {
        response: {
          status: 422,
          data: {
            detail: [
              { loc: ['body', 'start_date'], msg: 'invalid date format' },
              { loc: ['body', 'interval_days'], msg: 'must be positive' },
            ],
          },
          headers: {},
        },
      }) as never;
    });

    await expect(api.get('/x')).rejects.toBeTruthy();
    expect(toast.error).toHaveBeenCalledWith(
      '参数校验失败',
      expect.objectContaining({
        description: expect.stringContaining(
          'start_date: invalid date format；interval_days: must be positive',
        ),
      }),
    );
  });

  it('ERR_CANCELED 静默:组件卸载取消请求不弹任何 toast', async () => {
    mockAdapter(() => {
      throw canceledError() as never;
    });

    await expect(api.get('/x')).rejects.toBeTruthy();
    expect(toast.error).not.toHaveBeenCalled();
    expect(toast.warning).not.toHaveBeenCalled();
  });

  it('503 服务不可用:提示后端重启/网关不可用并带 trace', async () => {
    mockAdapter(() => {
      throw Object.assign(new AxiosError('Service Unavailable'), {
        response: {
          status: 503,
          data: {},
          headers: { 'trace-id': 'abcdef1234567890' },
        },
      }) as never;
    });

    await expect(api.get('/x')).rejects.toBeTruthy();
    expect(toast.error).toHaveBeenCalledWith(
      '服务暂时不可用',
      expect.objectContaining({
        description: expect.stringContaining('abcdef12'),
      }),
    );
  });

  it('401 未登录:写 flash 消息并跳登录页', async () => {
    // jsdom 不支持 location 导航赋值(会抛 Not implemented 且不改变 href),
    // 用 stub 捕获 redirectLogin 的跳转目标
    const locationStub = { href: '', pathname: '/', search: '' };
    vi.stubGlobal('location', locationStub);

    mockAdapter(() => {
      throw Object.assign(new AxiosError('Unauthorized'), {
        response: {
          status: 401,
          data: { msg: '登录已过期，请重新登录' },
          headers: {},
        },
      }) as never;
    });

    await expect(api.get('/x')).rejects.toBeTruthy();
    expect(sessionStorage.getItem(AUTH_FLASH_KEY)).toBe(
      '登录已过期，请重新登录',
    );
    expect(locationStub.href).toContain('/auth/login');
    vi.unstubAllGlobals();
  });
});
