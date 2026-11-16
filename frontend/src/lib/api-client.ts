// src/lib/api-client.ts —— axios 实例 + 统一拦截器(Bearer 注入/响应解包/错误 toast)
import Axios, { InternalAxiosRequestConfig } from 'axios';
import { toast } from 'sonner';

import { env } from '@/config/env';
import { paths } from '@/config/paths';

// FastAPI 统一响应体类型
interface ApiResponse<T = unknown> {
  code: number;
  msg: string;
  data: T;
  success: boolean;
  time: string;
}

// 1. 请求拦截器(Bearer 注入)
function authRequestInterceptor(config: InternalAxiosRequestConfig) {
  if (config.headers) {
    config.headers.Accept = 'application/json';
    // 鉴权适配:从 localStorage 读取登录时保存的 token
    const token = localStorage.getItem('app_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  config.withCredentials = true;
  return config;
}

export const api = Axios.create({
  baseURL: env.API_URL,
  // 30s 兜底超时(axios 默认 0 = 永久等待):慢接口至少可感知失败而非无限悬挂
  timeout: 30_000,
});

api.interceptors.request.use(authRequestInterceptor);

// 2. 响应拦截器(业务码分流 + 平铺/包裹两种响应形态统一解包 + 网络层失败自动重试)
api.interceptors.response.use(
  (response) => {
    // 二进制响应(下载导入模板等)没有 JSON 信封,直接回 data 交给落盘工具,
    // 不能按 code/msg 解包(碰巧透传不算数,语义上这里就该短路)
    if (response.config.responseType === 'blob') {
      return response.data as any;
    }
    const traceId = response.headers['trace-id'] as string | undefined;
    const body = response.data as ApiResponse;

    if (traceId) {
      (body as any).__traceId = traceId;
    }

    // 业务错误(HTTP 200 但 success===false)：统一分流
    if (body.success === false) {
      handleBusinessError(body);
      return Promise.reject(body);
    }

    // 原: return body.data as any;
    // 改: 分页响应(rows 平铺顶层无 data 字段)——整包返回供 fetcher 自取 rows/total
    return (body.data !== undefined ? body.data : body) as any;
  },
  (error) => {
    // 网络层失败(无 response)先自动重试,重试耗尽再走错误分流
    if (shouldRetryNetworkError(error)) {
      return retryRequest(error);
    }
    // HTTP 错误：统一分流
    handleHttpError(error);
    return Promise.reject(error);
  },
);

// 3. 网络层失败自动重试(仅幂等方法)
// 背景:后端 lifespan(Redis 连接池/建表/种子数据)启动需数秒,而 Vite 秒起即发
// 首屏请求,连接被拒/中断的响应没有任何头——浏览器一律误报成"跨域错误",
// 用户只能刷新页面。仅对 GET/HEAD/OPTIONS 的无 response 失败重试。
// **写方法(POST/PUT/DELETE/PATCH)禁止自动重试**(2026-10-22 实证):无 response
// ≠ 服务端未处理——响应在传输中丢失时服务端可能已成功落库(赎回响应丢失→
// axios 30s 超时→自动重发 POST→撞防重守卫 601,用户只点了一次却收到"重复
// 提交")。超时(ECONNABORTED)同样不重试:服务端已收到且在处理。
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1_000;
type RetryableConfig = InternalAxiosRequestConfig & { __retryCount?: number };

const IDEMPOTENT_METHODS = new Set(['get', 'head', 'options']);

function shouldRetryNetworkError(error: any): boolean {
  const config = error.config as RetryableConfig | undefined;
  if (!config) return false;
  // 超时:服务端已收到且在处理,重发可能造成重复交易
  if (error.code === 'ECONNABORTED') return false;
  // 非幂等方法:响应丢失 ≠ 服务端未处理,重发可能重复交易
  if (!IDEMPOTENT_METHODS.has((config.method ?? '').toLowerCase()))
    return false;
  return (config.__retryCount ?? 0) < MAX_RETRIES;
}

async function retryRequest(error: any): Promise<any> {
  const config = error.config as RetryableConfig;
  config.__retryCount = (config.__retryCount ?? 0) + 1;
  await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
  // 重发会再次经过请求拦截器(Bearer 重注入,幂等);若重试成功则上层完全无感
  return api.request(config);
}

// 4. 错误处理工具函数（sonner 官方 API:纯函数,拦截器等非组件代码直接调用）
function notify(type: 'error' | 'warning', title: string, message: string) {
  toast[type](title, { description: message });
}

/**
 * 跳登录页。带 reason 时走 flash message 模式:
 * window.location.href 整页跳转会销毁所有 toast(跳转前的提示用户根本看不到),
 * 因此把提示写进 sessionStorage,由登录页挂载时读取展示(跨页面跳转的标准做法)。
 */
function redirectLogin(reason?: string) {
  // 已经在登录页时不再跳转(避免登录失败 401 触发循环刷新,清掉 toast)
  if (window.location.pathname.startsWith(paths.auth.login.path)) {
    return;
  }
  if (reason) {
    sessionStorage.setItem(AUTH_FLASH_KEY, reason);
  }
  const redirectTo =
    new URLSearchParams(window.location.search).get('redirectTo') ||
    window.location.pathname;
  window.location.href = paths.auth.login.getHref(redirectTo);
}

/** 401 跳登录页时写给登录页展示的 flash 消息 key */
export const AUTH_FLASH_KEY = 'auth_flash_msg';

function withTrace(msg: string, traceId?: string) {
  return traceId ? `${msg}（trace: ${traceId.slice(0, 8)}）` : msg;
}

function handleHttpError(error: any) {
  // 1. 请求被取消静默:React Query 组件卸载/竞态取消会 abort 请求(axios 抛
  //    ERR_CANCELED),这是正常行为不该打扰用户——必须放在网络层判断之前
  if (error.code === 'ERR_CANCELED') {
    return;
  }

  // 2. 网络层错误（无 response,已按方法判定重试与否）——区分于浏览器误导性的"跨域",
  //    明确指向后端未就绪/网络中断两个真实原因
  if (!error.response) {
    const method = (error.config?.method ?? '').toLowerCase();
    if (IDEMPOTENT_METHODS.has(method)) {
      // 幂等查询:重试耗尽仍失败,就是后端没就绪
      notify(
        'error',
        '服务不可用',
        '后端服务未就绪或网络中断（已自动重试 2 次），请确认后端已启动后刷新',
      );
    } else {
      // 写操作:不自动重试(响应丢失≠未处理,重发可能重复交易)——
      // 结果未知,必须引导用户刷新核实,而不是盲目重试
      notify(
        'error',
        '网络异常，操作结果未知',
        '请求可能未成功，请刷新页面核实后再操作（请勿直接重复提交）',
      );
    }
    return;
  }

  const status = error.response?.status;
  const body = error.response?.data; // FastAPI 统一响应体
  const traceId = error.response?.headers?.['trace-id'];

  // 3. HTTP 状态码分流
  switch (status) {
    case 400:
      notify('error', '请求错误', body?.msg || '请求参数有误，请检查后重试');
      break;
    case 401:
      // notify 会死于整页跳转,真正可见的是 flash(登录页展示)
      notify('error', '未登录', body?.msg || '请重新登录');
      redirectLogin(body?.msg || '登录已过期，请重新登录');
      break;
    case 403:
      notify('error', '无权限', body?.msg || '无权限访问该资源');
      break;
    case 404:
      notify(
        'error',
        '资源不存在',
        body?.msg || '请求的资源不存在，可能已被删除',
      );
      break;
    case 408:
      notify('error', '请求超时', '服务端处理超时，请稍后重试');
      break;
    case 409:
      notify(
        'warning',
        '操作冲突',
        body?.msg || '数据已被修改或重复提交，请刷新后重试',
      );
      break;
    case 422: {
      // FastAPI 的 Pydantic 校验错误:真实信息在 detail 数组而非 msg
      notify(
        'error',
        '参数校验失败',
        parseValidationDetail(body, error.message),
      );
      break;
    }
    case 429: {
      // 后端超限响应带 Retry-After 头(秒)——读它给精确提示
      const retryAfter = error.response?.headers?.['retry-after'];
      const hint = retryAfter ? `,请 ${retryAfter} 秒后再试` : ',请稍后重试';
      notify('error', '限流', `请求过于频繁${hint}`);
      break;
    }
    case 500:
      notify('error', '服务器错误', withTrace(body?.msg, traceId));
      break;
    case 502:
    case 503:
    case 504:
      // 后端重启窗口/网关不可用/上游超时——冷启动与部署场景常见,提示等一会
      notify(
        'error',
        '服务暂时不可用',
        withTrace('后端正在重启或网关不可用，请稍后刷新重试', traceId),
      );
      break;
    default:
      notify('error', '请求失败', body?.msg || error.message);
  }
}

/** 422 detail 单条形如 {loc:['body','field'], msg:'...'},取 loc 末位为字段名 */
function parseValidationDetail(body: any, fallback: string): string {
  const detail = body?.detail;
  if (!detail) {
    return body?.msg || fallback;
  }
  const text = Array.isArray(detail)
    ? detail
        .map(
          (item: any) =>
            `${item.loc?.[item.loc.length - 1] ?? '字段'}: ${item.msg ?? '校验失败'}`,
        )
        .join('；')
    : String(detail);
  // 过长截断:toast description 塞几十条校验信息不可读
  return text.length > 200 ? `${text.slice(0, 200)}…` : text;
}

function handleBusinessError(body: ApiResponse) {
  const traceId = (body as any).__traceId as string | undefined;

  // 业务码分流（HTTP 200 但 success === false）
  switch (body.code) {
    case 401: {
      // 只有"带着 token 却 401"才是会话失效；无 token 的 401 是启动探测，静默
      if (localStorage.getItem('app_token')) {
        localStorage.removeItem('app_token');
        notify('error', '未登录', body.msg);
        redirectLogin(body.msg || '登录已过期，请重新登录');
      }
      break;
    }
    case 403:
      notify('error', '无权限', body.msg);
      break;
    case 601:
      notify('warning', '操作失败', body.msg); // 601 用 warning 色
      break;
    case 500:
      notify('error', '服务器错误', withTrace(body.msg, traceId));
      break;
    default:
      notify('error', '请求失败', body.msg);
  }
}
