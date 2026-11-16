// src/features/logs/api/get-logs.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api-client';
import { mapPage, PageResponse } from '@/lib/pagination';

// ===== 类型 =====

/** 列表行(窄字段):后端 2026-08-30 列表接口已窄字段投影——
 * operParam/jsonResult/errorMsg 大字段不进列表(实测单条 jsonResult 曾达 7 亿字符,
 * SELECT * 物化即秒级慢查询);详情走 useOperLogDetail 单查 */
export type SystemOperLog = {
  operId: number;
  title: string;
  businessType: number;
  method: string | null;
  requestMethod: string | null;
  operName: string;
  operUrl: string;
  operIp: string;
  status: number;
  costTime: number;
  operTime: string | null;
  category: string;
};

/** 详情行(全量含大字段):GET /system/log/{oper_id} 单查返回 */
export type SystemOperLogDetail = SystemOperLog & {
  deptName: string | null;
  operParam: string | null;
  jsonResult: string | null;
  errorMsg: string | null;
};

/** 日志类别(与后端 common.constants.LogCategory 同值):
 * category 是服务端分流锚点(DAO 必过滤),收常量避免页面散落字面量 */
export const LOG_CATEGORIES = {
  operation: 'operation',
  login: 'login',
} as const;

export type LogCategory = keyof typeof LOG_CATEGORIES;

/** 日志过滤参数(空值不发——后端动态 SQL 判空跳过) */
export type LogFilters = {
  category: LogCategory;
  title?: string;
  operName?: string;
  status?: string;
  beginTime?: string;
  endTime?: string;
};

// ===== 查询 =====

export const getOperLogs = (
  params: LogFilters & { pageNum: number; pageSize: number },
) =>
  api
    .get('/system/log/list', { params })
    // 拦截器运行时已解包(平铺对象),类型签名仍是 AxiosResponse(同 users 的双重转换)
    .then((res) =>
      mapPage<SystemOperLog>(res as unknown as PageResponse<SystemOperLog>),
    );

export const useOperLogs = (
  pageNum: number,
  pageSize: number,
  filters: LogFilters,
) =>
  useQuery({
    // filters 整体进 key:category/搜索/状态/时间任一变化即重取
    queryKey: ['oper-logs', pageNum, pageSize, filters],
    queryFn: () => getOperLogs({ ...filters, pageNum, pageSize }),
  });

// ===== 详情单查 =====

export const useOperLogDetail = (operId: number | null) =>
  useQuery({
    // enabled: 抽屉打开(有 id)才请求——按需加载大字段
    queryKey: ['oper-log', operId],
    queryFn: () =>
      api
        .get(`/system/log/${operId}`)
        .then((res) => res as any as SystemOperLogDetail),
    enabled: operId != null,
  });

// ===== 变更 =====

export const useDeleteOperLog = () => {
  const queryClient = useQueryClient();
  return useMutation({
    // 后端契约:DELETE /system/log/{oper_ids}(路径参数,支持逗号分隔批量;物理删除不可恢复)
    mutationFn: (operIds: number | number[]) => {
      const ids = Array.isArray(operIds) ? operIds.join(',') : operIds;
      return api.delete(`/system/log/${ids}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['oper-logs'] });
    },
  });
};
