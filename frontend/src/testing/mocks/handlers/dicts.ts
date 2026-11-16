// src/testing/mocks/handlers/dicts.ts
import { http } from 'msw';

import { env } from '@/config/env';

import { networkDelay, requireAuth, successResponse } from '../utils';

// 种子字典数据（参考若依 RuoYi-Vue3 的 sys_dict_data 表）
// 后端类比：相当于 Redis 中预热的字典缓存
const dictStore: Record<
  string,
  Array<{
    dictLabel: string;
    dictValue: string;
    dictType: string;
    cssClass?: string;
  }>
> = {
  // 用户性别
  sys_user_sex: [
    {
      dictLabel: '男',
      dictValue: '0',
      dictType: 'sys_user_sex',
      cssClass: 'tag-primary',
    },
    {
      dictLabel: '女',
      dictValue: '1',
      dictType: 'sys_user_sex',
      cssClass: 'tag-danger',
    },
    {
      dictLabel: '未知',
      dictValue: '2',
      dictType: 'sys_user_sex',
      cssClass: 'tag-info',
    },
  ],
  // 状态：正常/停用
  sys_normal_disable: [
    {
      dictLabel: '正常',
      dictValue: '0',
      dictType: 'sys_normal_disable',
      cssClass: 'tag-success',
    },
    {
      dictLabel: '停用',
      dictValue: '1',
      dictType: 'sys_normal_disable',
      cssClass: 'tag-warning',
    },
  ],
  // 通知类型
  sys_notice_type: [
    { dictLabel: '通知', dictValue: '1', dictType: 'sys_notice_type' },
    { dictLabel: '公告', dictValue: '2', dictType: 'sys_notice_type' },
  ],
  // 指数同步状态(镜像后端种子 sys_index_sync_status)
  sys_index_sync_status: [
    { dictLabel: '已同步', dictValue: '1', dictType: 'sys_index_sync_status' },
    { dictLabel: '未同步', dictValue: '0', dictType: 'sys_index_sync_status' },
    { dictLabel: '已过期', dictValue: '2', dictType: 'sys_index_sync_status' },
  ],
  // 持仓状态(镜像后端种子 sys_position_status)
  sys_position_status: [
    { dictLabel: '正常', dictValue: '0', dictType: 'sys_position_status' },
    { dictLabel: '部分赎回', dictValue: '1', dictType: 'sys_position_status' },
    { dictLabel: '全部赎回', dictValue: '2', dictType: 'sys_position_status' },
  ],
};

export const dictsHandlers = [
  // GET /dict/data/type/:dictType — 返回指定类型的字典选项
  //   后端类比：从 Redis 字典缓存按 dictType 取数据
  http.get(
    `${env.API_URL}/dict/data/type/:dictType`,
    async ({ cookies, params }) => {
      await networkDelay();
      requireAuth(cookies);
      const dictType = params.dictType as string;
      const data = dictStore[dictType] ?? [];
      return successResponse(data);
    },
  ),
];
