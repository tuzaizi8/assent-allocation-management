// 处理中面板的单测:断言的是一条产品规则——处理期间面板里没有"选择文件"入口,
// 使用者不会顺手再导第二份(那正是撞上"已有重建正在进行"的触发条件)。
import { render, screen } from '@testing-library/react';

import { StatementImportProgress } from '@/features/statement-import/components/statement-import-progress';

test('显示进行中阶段、文件名与条数,且没有选择文件的入口', () => {
  render(
    <StatementImportProgress fileName="alipay-2026.pdf" recordCount={12} />,
  );

  // role=status 让读屏也能播报"正在做什么"
  expect(screen.getByRole('status')).toHaveTextContent(
    '正在导入并重建历史持仓',
  );
  expect(screen.getByText(/alipay-2026\.pdf · 12 条记录/)).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '选择文件' }),
  ).not.toBeInTheDocument();
});
