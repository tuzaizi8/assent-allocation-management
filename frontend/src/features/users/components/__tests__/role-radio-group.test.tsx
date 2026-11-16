// 角色单选组测试(需求修订 2026-08-27:全局单选,二选一互斥)
// 断言语义:选第二个角色 → 第一个自动被替换(用户要么管理员要么普通角色)
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import type { SystemRole } from '@/features/roles/api/get-roles';
import { RoleRadioGroup } from '@/features/users/components/role-radio-group';

const roles: SystemRole[] = [
  {
    roleId: 1,
    roleName: '超级管理员',
    roleKey: 'admin',
    roleSort: 1,
    status: '0',
    createTime: null,
    remark: null,
  },
  {
    roleId: 2,
    roleName: '普通角色',
    roleKey: 'common',
    roleSort: 2,
    status: '0',
    createTime: null,
    remark: null,
  },
  {
    roleId: 3,
    roleName: '停用角色',
    roleKey: 'disabled',
    roleSort: 3,
    status: '1',
    createTime: null,
    remark: null,
  },
];

function Harness() {
  const [roleId, setRoleId] = useState<number | null>(null);
  return (
    <div>
      <RoleRadioGroup roles={roles} value={roleId} onChange={setRoleId} />
      <div data-testid="state">{roleId ?? 'null'}</div>
    </div>
  );
}

test('单选:选第二个角色自动替换第一个(二选一互斥)', async () => {
  const user = userEvent.setup();
  render(<Harness />);

  // 选第一个角色
  await user.click(screen.getByRole('radio', { name: /超级管理员/ }));
  expect(screen.getByTestId('state')).toHaveTextContent('1');

  // 选第二个角色——第一个自动被替换(核心断言:互斥语义)
  await user.click(screen.getByRole('radio', { name: /普通角色/ }));
  expect(screen.getByTestId('state')).toHaveTextContent('2');
  expect(screen.getByTestId('state')).not.toHaveTextContent('1,');
});

test('点已选中项不取消(单选无法清空 = 必选语义)', async () => {
  const user = userEvent.setup();
  render(<Harness />);

  await user.click(screen.getByRole('radio', { name: /超级管理员/ }));
  // 再点一次已选中的——状态保持(Radix RadioGroup 天然行为)
  await user.click(screen.getByRole('radio', { name: /超级管理员/ }));
  expect(screen.getByTestId('state')).toHaveTextContent('1');
});

test('点 label 文字同样切换选中', async () => {
  const user = userEvent.setup();
  render(<Harness />);

  await user.click(screen.getByText('超级管理员'));
  expect(screen.getByTestId('state')).toHaveTextContent('1');

  await user.click(screen.getByText('普通角色'));
  expect(screen.getByTestId('state')).toHaveTextContent('2');
});

test('停用角色不可选', () => {
  render(<Harness />);
  // Radix disabled 项的 aria-disabled
  expect(screen.getByRole('radio', { name: /停用角色/ })).toBeDisabled();
});

test('form 上下文内单选正常(真实页面结构)', async () => {
  const user = userEvent.setup();
  render(
    <form onSubmit={(e) => e.preventDefault()}>
      <Harness />
    </form>,
  );

  await user.click(screen.getByRole('radio', { name: /超级管理员/ }));
  await user.click(screen.getByRole('radio', { name: /普通角色/ }));
  expect(screen.getByTestId('state')).toHaveTextContent('2');
});
