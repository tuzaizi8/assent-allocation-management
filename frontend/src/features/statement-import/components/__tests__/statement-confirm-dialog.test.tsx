// 导入二次确认弹窗的单测:断言的是一条产品规则——「这是导入,不是删除」,
// 所以不能出现删除的红色/破坏性语义;以及点确认会把动作交回调用方。
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { StatementConfirmDialog } from '@/features/statement-import/components/statement-confirm-dialog';

const renderDialog = (onConfirm: () => void = () => {}) =>
  render(
    <StatementConfirmDialog
      open
      onOpenChange={() => {}}
      title="确认导入 3 条记录？"
      description="按「支付宝」累加"
      confirmText="确认导入"
      onConfirm={onConfirm}
    />,
  );

test('标题与说明原文照显,确认按钮走主色而不是删除的红色', () => {
  renderDialog();

  expect(screen.getByText('确认导入 3 条记录？')).toBeInTheDocument();
  expect(screen.getByText('按「支付宝」累加')).toBeInTheDocument();
  // 主色 = variant 默认值;删除弹窗那套是 destructive,套过来会让人以为在删数据
  const confirmButton = screen.getByRole('button', { name: '确认导入' });
  expect(confirmButton).toHaveAttribute('data-variant', 'default');
});

test('点确认把动作交回调用方', async () => {
  const user = userEvent.setup();
  const onConfirm = vi.fn();
  renderDialog(onConfirm);

  await user.click(screen.getByRole('button', { name: '确认导入' }));

  expect(onConfirm).toHaveBeenCalledTimes(1);
});
