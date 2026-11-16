// src/lib/pagination.ts
import { Meta } from '@/types/api';

/** 后端分页平铺响应(方案 A:rows/pageNum 等在响应体顶层,经拦截器整包返回) */
export interface PageResponse<T> {
  rows: T[];
  pageNum: number;
  pageSize: number;
  total: number;
  hasNext: boolean;
}

/** 分页 fetcher 标准返回:组件只消费 data/meta,不触碰平铺字段 */
export type Paged<T> = { data: T[]; meta: Meta };

/**
 * 后端平铺分页 → 前端 {data, meta} 统一映射
 *
 * 后端类比:相当于后端 DO→VO 的转换层——把"数据库风格"的分页结构
 * 适配成"前端风格",消费方只见标准形态。
 */
export const mapPage = <T>(res: PageResponse<T>): Paged<T> => ({
  data: res.rows,
  meta: {
    currentPage: res.pageNum,
    totalPages: Math.ceil(res.total / res.pageSize),
    totalItems: res.total,
    itemCount: res.rows.length,
    itemsPerPage: res.pageSize,
  },
});
