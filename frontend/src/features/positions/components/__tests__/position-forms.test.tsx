// 持仓写操作表单的控件形态单测:买入/赎回日期必须是共享的 shadcn 日历字段(带日历图标的按钮),
// 不再是系统原生 date 输入——同一页两套控件形态是实测反馈过的问题。
import { vi } from 'vitest';

import type { PositionDetail } from '@/features/positions/api/get-positions';
import {
  RedeemForm,
  TradeForm,
} from '@/features/positions/components/position-forms';
import { createUser, renderApp, screen, userEvent } from '@/testing/test-utils';

/** 赎回表单只消费 fundName/fundCode/totalShares,局部对象 + as 断言即可(同 combobox 测试的 as Fund) */
const POSITION = {
  fundName: '华夏大盘精选混合',
  fundCode: '000011',
  totalShares: 1000,
} as PositionDetail;

// 组件挂在 AuthLoader 之后(登录态未就绪时整棵树是 spinner),字段必须 findBy 等出来
const findDateTrigger = () => screen.findByLabelText('选择日期');

test('买入日期是 shadcn 日历字段,不是原生 date 输入', async () => {
  const user = userEvent.setup();
  await renderApp(<TradeForm mode="purchase" onDone={vi.fn()} />, {
    user: await createUser(),
  });

  const trigger = await findDateTrigger();
  expect(trigger.tagName).toBe('BUTTON');
  expect(document.querySelector('input[type="date"]')).toBeNull();

  await user.click(trigger);
  expect(await screen.findByRole('grid')).toBeInTheDocument();
});

test('赎回日期同款(同一页不留原生 date 控件)', async () => {
  const user = userEvent.setup();
  await renderApp(
    <RedeemForm position={POSITION} onSubmit={vi.fn()} onDone={vi.fn()} />,
    { user: await createUser() },
  );

  const trigger = await findDateTrigger();
  expect(trigger.tagName).toBe('BUTTON');
  expect(document.querySelector('input[type="date"]')).toBeNull();

  await user.click(trigger);
  expect(await screen.findByRole('grid')).toBeInTheDocument();
});
