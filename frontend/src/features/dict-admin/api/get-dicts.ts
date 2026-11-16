// src/features/dict-admin/api/get-dicts.ts
// 字典管理域(管理端 CRUD):与 features/dict(消费域,只读)边界同 menu / menu-admin
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from '@/lib/api-client';
import { mapPage, PageResponse } from '@/lib/pagination';

// ===== 类型 =====

/** 后端 sys_dict_type 行(分页 rows 元素,后端 to_camel 已转驼峰) */
export type SystemDictType = {
  dictId: number;
  dictName: string;
  dictType: string;
  status: string | null;
  createTime: string | null;
};

/** 后端 sys_dict_data 行(按类型全量返回,不分页) */
export type SystemDictData = {
  dictCode: number;
  dictSort: number | null;
  dictLabel: string;
  dictValue: string;
  dictType: string;
  cssClass: string | null;
  status: string | null;
  createTime: string | null;
};

// ===== 查询:字典类型(分页契约,同用户管理) =====

export const getDictTypes = (params: {
  pageNum: number;
  pageSize: number;
  dictName?: string;
}) =>
  api
    .get('/dict/type/list', { params })
    .then((res) =>
      mapPage<SystemDictType>(res as unknown as PageResponse<SystemDictType>),
    );

export const useDictTypes = (
  pageNum: number,
  pageSize: number,
  dictName?: string,
) =>
  useQuery({
    queryKey: ['dict-types', pageNum, pageSize, dictName ?? ''],
    queryFn: () => getDictTypes({ pageNum, pageSize, dictName }),
  });

// ===== 查询:字典数据(按类型全量,不分页) =====

export const getDictDataList = (dictType: string) =>
  api.get('/dict/data/list', { params: { dictType } }) as Promise<
    SystemDictData[]
  >;

export const useDictDataList = (dictType: string) =>
  useQuery({
    queryKey: ['dict-data-list', dictType],
    queryFn: () => getDictDataList(dictType),
    enabled: !!dictType,
  });

// ===== 变更:字典类型 =====

/** 新增字典类型表单校验(对齐后端 DictTypeAddModel) */
export const addDictTypeSchema = z.object({
  dictName: z.string().min(1, '必填').max(100, '最多 100 字'),
  dictType: z
    .string()
    .min(1, '必填')
    .max(100, '最多 100 字')
    .regex(/^sys_[a-z0-9_]+$/, '建议 sys_ 前缀 + 小写字母数字下划线'),
  status: z.enum(['0', '1']).default('0'),
});
export type AddDictTypeInput = z.infer<typeof addDictTypeSchema>;

/** 编辑字典类型表单校验(内置类型的标识禁改由后端兜底) */
export const editDictTypeSchema = z.object({
  dictId: z.number(),
  dictName: z.string().min(1, '必填').max(100, '最多 100 字'),
  dictType: z.string().min(1, '必填').max(100, '最多 100 字'),
  status: z.enum(['0', '1']),
});
export type EditDictTypeInput = z.infer<typeof editDictTypeSchema>;

/** 写操作成功后统一失效:类型列表 + 消费域 useDict(['dict', dictType]) 缓存 */
const invalidateDictCaches = (
  queryClient: ReturnType<typeof useQueryClient>,
) => {
  queryClient.invalidateQueries({ queryKey: ['dict-types'] });
  queryClient.invalidateQueries({ queryKey: ['dict-data-list'] });
  queryClient.invalidateQueries({ queryKey: ['dict'] });
};

export const useAddDictType = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: AddDictTypeInput) => api.post('/dict/type', data),
    onSuccess: () => invalidateDictCaches(queryClient),
  });
};

export const useEditDictType = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: EditDictTypeInput) => api.put('/dict/type', data),
    onSuccess: () => invalidateDictCaches(queryClient),
  });
};

export const useDeleteDictType = () => {
  const queryClient = useQueryClient();
  return useMutation({
    // 后端契约:DELETE /dict/type/{dict_ids}(路径参数,支持逗号分隔批量)
    mutationFn: (dictIds: number | number[]) => {
      const ids = Array.isArray(dictIds) ? dictIds.join(',') : dictIds;
      return api.delete(`/dict/type/${ids}`);
    },
    onSuccess: () => invalidateDictCaches(queryClient),
  });
};

// ===== 变更:字典数据 =====

/** 新增字典数据表单校验(对齐后端 DictDataAddModel) */
export const addDictDataSchema = z.object({
  dictLabel: z.string().min(1, '必填').max(100, '最多 100 字'),
  dictValue: z.string().min(1, '必填').max(100, '最多 100 字'),
  dictSort: z.coerce.number().int('必须为整数').min(0, '不能为负'),
  cssClass: z.string().max(100, '最多 100 字').or(z.literal('')).optional(),
  status: z.enum(['0', '1']).default('0'),
});
export type AddDictDataInput = z.infer<typeof addDictDataSchema>;

/** 编辑字典数据表单校验(所属类型不允许修改,后端兜底) */
export const editDictDataSchema = z.object({
  dictCode: z.number(),
  dictLabel: z.string().min(1, '必填').max(100, '最多 100 字'),
  dictValue: z.string().min(1, '必填').max(100, '最多 100 字'),
  dictSort: z.coerce.number().int('必须为整数').min(0, '不能为负'),
  cssClass: z.string().max(100, '最多 100 字').or(z.literal('')).optional(),
  status: z.enum(['0', '1']),
});
export type EditDictDataInput = z.infer<typeof editDictDataSchema>;

export const useAddDictData = (dictType: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: AddDictDataInput) =>
      api.post('/dict/data', { ...data, dictType }),
    onSuccess: () => invalidateDictCaches(queryClient),
  });
};

export const useEditDictData = (dictType: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: EditDictDataInput) =>
      api.put('/dict/data', { ...data, dictType }),
    onSuccess: () => invalidateDictCaches(queryClient),
  });
};

export const useDeleteDictData = () => {
  const queryClient = useQueryClient();
  return useMutation({
    // 后端契约:DELETE /dict/data/{dict_ids}(路径参数,支持逗号分隔批量)
    mutationFn: (dictCodes: number | number[]) => {
      const ids = Array.isArray(dictCodes) ? dictCodes.join(',') : dictCodes;
      return api.delete(`/dict/data/${ids}`);
    },
    onSuccess: () => invalidateDictCaches(queryClient),
  });
};
