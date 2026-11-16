// src/features/roles/components/menu-tree-checkbox.tsx
// 角色配菜单的勾选树:复用菜单管理页的全量菜单数据(features/menu-admin 域)
import { useMemo } from 'react';

import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import { useDictLabel } from '@/features/dict/api/get-dict';
import type { SystemMenu } from '@/features/menu-admin/api/get-admin-menus';

interface MenuTreeNode {
  menu: SystemMenu;
  children: MenuTreeNode[];
}

interface MenuTreeCheckboxProps {
  /** 全量菜单(平铺,来自 useAdminMenus) */
  menus: SystemMenu[];
  /** 已勾选的 menuId 集合 */
  checked: number[];
  onChange: (checked: number[]) => void;
}

/** 平铺菜单 → 树(与后端 _build_tree 同构:dict 索引一次遍历) */
function buildTree(menus: SystemMenu[]): MenuTreeNode[] {
  const nodes = new Map<number, MenuTreeNode>();
  menus.forEach((m) => nodes.set(m.menuId, { menu: m, children: [] }));
  const roots: MenuTreeNode[] = [];
  menus.forEach((m) => {
    const node = nodes.get(m.menuId)!;
    const parent = nodes.get(m.parentId ?? 0);
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node); // 父不在集合 = 根(容错,同后端)
    }
  });
  const sortNodes = (list: MenuTreeNode[]) => {
    list.sort((a, b) => (a.menu.orderNum ?? 0) - (b.menu.orderNum ?? 0));
    list.forEach((n) => sortNodes(n.children));
  };
  sortNodes(roots);
  return roots;
}

/** 收集节点及其全部子孙 id(父勾选 = 勾全部子孙) */
function collectSubtreeIds(node: MenuTreeNode): number[] {
  return [node.menu.menuId, ...node.children.flatMap(collectSubtreeIds)];
}

/**
 * 菜单勾选树(受控组件)
 * 语义:勾父 = 勾全部子孙;取消父 = 取消全部子孙;不做半选(indeterminate)态——
 * 提交给后端的是勾选全集(全量替换语义,见后端 edit_role_services)
 */
export function MenuTreeCheckbox({
  menus,
  checked,
  onChange,
}: MenuTreeCheckboxProps) {
  const tree = useMemo(() => buildTree(menus), [menus]);
  // 类型副文案字典驱动(sys_menu_type;原为模块级 typeLabel 常量)
  const typeLabel = useDictLabel('sys_menu_type');

  const toggle = (node: MenuTreeNode) => {
    const ids = collectSubtreeIds(node);
    const allChecked = ids.every((id) => checked.includes(id));
    if (allChecked) {
      onChange(checked.filter((id) => !ids.includes(id)));
    } else {
      onChange([...new Set([...checked, ...ids])]);
    }
  };

  const renderNodes = (nodes: MenuTreeNode[], depth: number) =>
    nodes.map((node) => {
      const subtreeIds = collectSubtreeIds(node);
      const isChecked = subtreeIds.every((id) => checked.includes(id));
      return (
        <div key={node.menu.menuId} style={{ paddingLeft: depth * 16 }}>
          <label className="flex items-center gap-1.5 py-0.5 text-sm">
            <input
              type="checkbox"
              checked={isChecked}
              onChange={() => toggle(node)}
              className="size-4"
            />
            <span>{node.menu.menuName}</span>
            <span className="text-xs text-muted-foreground">
              {typeLabel(String(node.menu.menuType))}
              {node.menu.perms ? ` · ${node.menu.perms}` : ''}
            </span>
          </label>
          {node.children.length > 0 && renderNodes(node.children, depth + 1)}
        </div>
      );
    });

  if (menus.length === 0) {
    return (
      // 骨架与勾选树行同高,菜单请求返回时不跳版
      <div className="flex flex-col gap-2 rounded-md border p-3">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-4 w-full" />
        ))}
        <Spinner className="sr-only" />
      </div>
    );
  }

  return (
    <div className="max-h-[320px] space-y-0.5 overflow-y-auto rounded-md border p-3">
      {renderNodes(tree, 0)}
    </div>
  );
}
