// src/features/menu/types.ts

// 后端 /getRouters 返回的菜单节点类型（对应若依 sys_menu 表）
export interface MenuItem {
  id: number;
  parentId: number;
  name: string; // 菜单名称（显示文本 + 路由 name）
  path: string; // 路由路径，如 '/app/system/users'
  component: string; // 组件路径，如 'system/users'（前端按此映射懒加载）
  perms: string; // 权限标识，如 'system:user:list'
  menuType: 'M' | 'C'; // M=目录（分组） C=菜单（页面）
  visible: boolean; // 是否在侧边栏显示
  icon: string; // 菜单图标
  children?: MenuItem[]; // 子菜单（递归）
}
