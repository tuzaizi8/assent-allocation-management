// 基金选择器的选中语义单测:选中反馈落在输入框本身(被基金名称占用)而不是下方小字,
// 选中后收起候选;再输入即取消选中并重新展开搜索。只钉产品规则,不测实现细节。
// 候选走 /fund/candidates(公共参考数据,仅登录):选基金是建仓/买入的核心路径,
// 不被「基金管理」菜单权限(fund:fund:list)卡住——三个用例都用零权限账号。
import { http } from 'msw';
import { useState } from 'react';

import { env } from '@/config/env';
import type { Fund } from '@/features/funds/api/get-funds';
import { FundCombobox } from '@/features/funds/components/fund-combobox';
import { server } from '@/testing/mocks/server';
import { successResponse } from '@/testing/mocks/utils';
import { createUser, renderApp, screen, userEvent } from '@/testing/test-utils';

const FUND = {
  fundId: 1,
  code: '000011',
  name: '华夏大盘精选混合',
} as Fund;

/** 候选接口是后端分页契约:mapPage 认 rows/total/pageNum/pageSize 四个字段 */
const stubFundCandidates = () =>
  server.use(
    http.get(`${env.API_URL}/fund/candidates`, () =>
      successResponse({ rows: [FUND], total: 1, pageNum: 1, pageSize: 10 }),
    ),
  );

/** 断言锚点:把组件回传的选中基金显示出来,同时提供输入框 */
function Harness() {
  const [fund, setFund] = useState<Fund | null>(null);
  return (
    <>
      <FundCombobox onChange={setFund} />
      <span data-testid="picked">{fund?.code ?? '未选'}</span>
    </>
  );
}

// 零权限账号:候选是公共参考数据,权限不该影响选择器
const renderCombobox = async () => {
  const view = await renderApp(<Harness />, {
    user: await createUser({ permissions: [] }),
  });
  const input = await screen.findByPlaceholderText('输入基金代码或名称搜索');
  return { ...view, input };
};

test('选中候选后输入框被基金名称占用,候选列表收起', async () => {
  stubFundCandidates();
  const user = userEvent.setup();
  const { input } = await renderCombobox();

  await user.type(input, '000011');
  await user.click(await screen.findByText(FUND.name));

  expect(input).toHaveValue(FUND.name);
  // 反馈不再靠小字
  expect(screen.queryByText(/已选基金代码/)).not.toBeInTheDocument();
  // 列表收起:候选列表(listbox)整体从文档里消失
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  // 选中已回传调用方(表单据此写 fundCode / 按钮据此解除禁用)
  expect(screen.getByTestId('picked')).toHaveTextContent(FUND.code);
});

test('选中后再输入即取消选中并重新展开搜索', async () => {
  stubFundCandidates();
  const user = userEvent.setup();
  const { input } = await renderCombobox();

  await user.type(input, '000011');
  await user.click(await screen.findByText(FUND.name));
  expect(screen.getByTestId('picked')).toHaveTextContent(FUND.code);

  // 再点输入框:聚焦即全选,键入整串替换 → 取消选中 + 重新展开候选
  await user.click(input);
  await user.keyboard('华夏');

  expect(screen.getByTestId('picked')).toHaveTextContent('未选');
  expect(await screen.findByText(FUND.name)).toBeInTheDocument();
});

test('无 fund:fund:list 权限也能搜索候选(公共端点,仅登录)', async () => {
  stubFundCandidates();
  const user = userEvent.setup();
  const { input } = await renderCombobox();

  await user.type(input, '000011');

  // 选择器的候选走 /fund/candidates(公共参考数据),不再被管理页菜单权限卡住
  expect(await screen.findByText(FUND.name)).toBeInTheDocument();
});
