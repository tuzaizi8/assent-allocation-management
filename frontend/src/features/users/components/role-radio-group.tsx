// src/features/users/components/role-radio-group.tsx
// 用户分配角色的单选组:受控组件(全局单选语义——一个用户要么管理员要么普通角色,
// 二选一互斥;需求修订 2026-08-27,初版多选勾选组已废弃)
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import type { SystemRole } from '@/features/roles/api/get-roles';

interface RoleRadioGroupProps {
  /** 全量角色(平铺,来自 useRoleOptions 大页拉取) */
  roles: SystemRole[];
  /** 选中的 roleId(null = 未选) */
  value: number | null;
  onChange: (roleId: number) => void;
}

/**
 * 角色单选组(受控组件)
 * 语义:全局单选——选新角色自动替换旧角色;点已选中项不取消(Radix 单选无法清空);
 * 停用角色(status='1')不可新选,已绑定仍可见;
 * 提交给后端的是单元素数组 [roleId](全量替换语义,见后端 edit_user_services)
 */
export function RoleRadioGroup({
  roles,
  value,
  onChange,
}: RoleRadioGroupProps) {
  if (roles.length === 0) {
    return (
      // 骨架与真实单选行同高:角色请求返回时不跳版
      <div className="flex flex-col gap-2 rounded-md border p-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-4 w-full" />
        ))}
        <Spinner className="sr-only" />
      </div>
    );
  }

  return (
    <div className="max-h-[200px] overflow-y-auto rounded-md border p-3">
      {/* Radix RadioGroup 的 value 是字符串(数字 roleId 需转换) */}
      <RadioGroup
        value={value != null ? String(value) : ''}
        onValueChange={(v) => onChange(Number(v))}
        className="gap-1"
      >
        {roles.map((role) => (
          <div key={role.roleId} className="flex items-center gap-1.5 py-0.5">
            <RadioGroupItem
              value={String(role.roleId)}
              id={`role-${role.roleId}`}
              disabled={role.status === '1'}
            />
            <Label
              htmlFor={`role-${role.roleId}`}
              className="flex items-center gap-1.5 py-0.5 text-sm font-normal"
            >
              {role.roleName}
              <span className="text-xs text-muted-foreground">
                {role.roleKey}
              </span>
            </Label>
          </div>
        ))}
      </RadioGroup>
    </div>
  );
}
