// 此文件用于存放与后端 API 对齐的类型定义
// 理想情况下应由后端 schema 自动生成，现阶段先手写基础类型

/**
 * 所有实体的基类
 * - id: 实体唯一标识，用作 React key
 * - createdAt: 创建时间戳（秒），用于排序
 */
export type BaseEntity = {
  id: string;
  createdAt: number;
};

/**
 * 实体工具类型：把任意对象类型扩展为带 id/createdAt 的完整实体
 * 用法：type User = Entity<{ name: string; email: string }>;
 */
export type Entity<T> = {
  [K in keyof T]: T[K];
} & BaseEntity;

// src/types/api.ts
export type Meta = {
  currentPage: number;
  totalPages: number;
  totalItems: number;
  itemCount: number;
  itemsPerPage: number;
};

export type User = {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: 'ADMIN' | 'USER';
  permissions: string[]; // 新增：权限标识列表，如 ['system:user:list', 'system:user:add']
};

export type AuthResponse = {
  jwt: string; // Cookie 模式下前端不读，仅类型占位
  user: User;
};

export type RegisterInput = {
  email: string;
  password: string;
  /** 昵称:落 sys_user.nick_name;读侧映射回 User.firstName 展示 */
  nickName: string;
};
