// 导入预览表单测:勾选语义与分级展示
// 断言的是一条产品规则——「错误行不可提交、告警行可提交、默认全选」,
// 这三条决定了用户按一次确认到底会把哪些记录写进持仓账本。
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { TooltipProvider } from '@/components/ui/tooltip';
import type {
  StatementPreviewResult,
  StatementPreviewRow,
} from '@/features/statement-import/api/statement-import';
import { StatementPreview } from '@/features/statement-import/components/statement-preview';

const makeRow = (
  overrides: Partial<StatementPreviewRow> &
    Pick<StatementPreviewRow, 'row' | 'fundCode' | 'fundName' | 'type'>,
): StatementPreviewRow => ({
  date: '2026-05-08',
  dividend: '',
  amount: 100,
  shares: 80,
  unitPrice: 1.25,
  fee: 0,
  orderNo: null,
  status: 'pending',
  page: 1,
  layer: 'text',
  confidence: 0.99,
  adapter: 'alipay',
  navPending: false,
  resolveNote: '',
  ...overrides,
});

const baseResult: StatementPreviewResult = {
  preview: [
    makeRow({
      row: 2,
      fundCode: '000001',
      fundName: '华夏成长混合',
      type: '买入',
    }),
    makeRow({
      row: 3,
      fundCode: '110011',
      fundName: '易方达中小盘',
      type: '赎回',
      amount: 21.3,
      shares: 10.5,
      unitPrice: 2.03,
    }),
    makeRow({
      row: 4,
      fundCode: '161725',
      fundName: '招商中证白酒',
      type: '买入',
      amount: 500,
      shares: 400,
    }),
  ],
  summary: {
    purchases: 2,
    redemptions: 1,
    total: 3,
    warnings: 1,
    adapter: 'alipay',
    adapterName: '支付宝',
    mode: 'table',
    kind: 'excel',
    ocrUsed: false,
    parsed: 4,
  },
  // 错误行只在 errors 里:后端已把它从 preview 剔除,永远不会被提交
  errors: [
    {
      error: '基金代码「12A45」不是 6 位数字',
      row: 5,
      field: 'fundCode',
      page: 1,
    },
  ],
  warnings: [
    {
      error: '金额与 份额×净值 差 0.01 元（手续费/四舍五入）',
      row: 2,
      field: 'amount',
      page: 1,
    },
  ],
};

function renderPreview(result: StatementPreviewResult = baseResult) {
  const onConfirm = vi.fn();
  const onReset = vi.fn();
  render(
    <TooltipProvider>
      <StatementPreview
        result={result}
        onConfirm={onConfirm}
        onReset={onReset}
      />
    </TooltipProvider>,
  );
  return { onConfirm, onReset };
}

test('默认全选可提交行:确认按钮显示待提交条数', () => {
  renderPreview();
  expect(screen.getByRole('button', { name: /确认导入 3 条/ })).toBeEnabled();
});

test('分红行在类型列显示红利再投资/现金分红徽标,而不是笼统的买入', () => {
  // 账本没有独立分红表(分红落在买入/赎回表里),类型列的这两枚标签就是分红行的身份
  const result: StatementPreviewResult = {
    ...baseResult,
    preview: [
      makeRow({
        row: 2,
        fundCode: '003547',
        fundName: '鹏华丰禄债券',
        type: '买入',
        dividend: '红利再投资',
        amount: 0,
        shares: 5.86,
        unitPrice: 0,
      }),
      makeRow({
        row: 3,
        fundCode: '003547',
        fundName: '鹏华丰禄债券',
        type: '买入',
        dividend: '现金分红',
        amount: -17.56,
        shares: 0,
        unitPrice: 0,
      }),
    ],
  };
  renderPreview(result);

  expect(screen.getByText('红利再投资')).toBeInTheDocument();
  expect(screen.getByText('现金分红')).toBeInTheDocument();
  // 概览文案里也有「买入」二字,负断言只看表格(预览页有主表 + 来源表两张):
  // 表里只有这两行分红,不应再出现「买入」徽标
  for (const table of screen.getAllByRole('table')) {
    expect(within(table).queryByText('买入')).not.toBeInTheDocument();
  }
});

test('取消勾选后只提交剩下的行', async () => {
  const user = userEvent.setup();
  const { onConfirm } = renderPreview();

  await user.click(screen.getByRole('checkbox', { name: '选择第 3 行记录' }));
  const confirmButton = screen.getByRole('button', { name: /确认导入 2 条/ });
  expect(confirmButton).toBeEnabled();

  await user.click(confirmButton);
  expect(onConfirm).toHaveBeenCalledTimes(1);
  const submitted = onConfirm.mock.calls[0][0] as StatementPreviewRow[];
  expect(submitted.map((item) => item.fundCode)).toEqual(['000001', '161725']);
});

test('全部取消勾选后确认按钮禁用', async () => {
  const user = userEvent.setup();
  renderPreview();

  for (const label of [
    '选择第 2 行记录',
    '选择第 3 行记录',
    '选择第 4 行记录',
  ]) {
    await user.click(screen.getByRole('checkbox', { name: label }));
  }

  expect(screen.getByRole('button', { name: /确认导入 0 条/ })).toBeDisabled();
});

test('错误行只出现在问题清单里,且没有可勾的入口', () => {
  renderPreview();

  expect(
    screen.getByText('有 1 条记录没有通过校验，不会被提交'),
  ).toBeInTheDocument();
  expect(
    screen.getByText('基金代码「12A45」不是 6 位数字'),
  ).toBeInTheDocument();
  // 错误行不放勾选框:后端已把它从 preview 里剔除,本来就没有可勾的东西
  expect(
    screen.queryByRole('checkbox', { name: '该行未通过校验，无法提交' }),
  ).not.toBeInTheDocument();
  // 待提交表里没有这条错误记录的痕迹
  expect(screen.queryByText('12A45')).not.toBeInTheDocument();
});

test('问题说明移到图标浮层里,正文只留标题与表格', () => {
  renderPreview();

  // 浮层未打开时不进 DOM:两句说明都不在正文
  expect(screen.queryByText(/数据本身不成立/)).not.toBeInTheDocument();
  expect(screen.queryByText(/手续费与四舍五入/)).not.toBeInTheDocument();
  // 标题仍在(说明只是换了承载方式,不是被删掉)
  expect(
    screen.getByText('有 1 条记录没有通过校验，不会被提交'),
  ).toBeInTheDocument();
  expect(screen.getByText('有 1 条记录带提示，可以提交')).toBeInTheDocument();
});

test('概览只给"哪个平台的什么文件",不暴露抽取模式与置信度', () => {
  renderPreview();

  expect(screen.getByText('支付宝')).toBeInTheDocument();
  expect(screen.getByText('Excel 明细')).toBeInTheDocument();
  expect(screen.queryByText('表头映射抽取')).not.toBeInTheDocument();
  expect(screen.queryByText(/平均置信度/)).not.toBeInTheDocument();
  // 条数在「解析记录」统计卡里、未通过条数在错误块标题里,徽标行不再重复一遍
  expect(screen.queryByText(/解析出/)).not.toBeInTheDocument();
});

test('待提交区不再复述业务口径,条数只在分页条上说一次', () => {
  renderPreview();

  // 卡片描述整段已删:新旧两种口径文案都不该再出现
  expect(screen.queryByText(/清空上一次导入的数据/)).not.toBeInTheDocument();
  expect(
    screen.queryByText(/与本平台已导入记录重复的会自动跳过/),
  ).not.toBeInTheDocument();
  // 条数改由分页条左侧承载,旧的「共 N 条」已撤
  expect(screen.getByText('已选 3 / 3 条')).toBeInTheDocument();
  expect(screen.queryByText(/共 3 条/)).not.toBeInTheDocument();
  // 标题保留在表格上方
  expect(screen.getByText('待提交记录')).toBeInTheDocument();
});

test('告警行仍可提交,并带黄色底标', () => {
  renderPreview();

  expect(screen.getByText('有 1 条记录带提示，可以提交')).toBeInTheDocument();
  // 告警与错误同款:原因落在表格行里(role=row 只存在于表格内),行内还有字段名
  const warningIssueRow = screen.getByRole('row', { name: /差 0.01 元/ });
  expect(within(warningIssueRow).getByText('amount')).toBeInTheDocument();
  // 整行可达名包含单元格文本,按行角色取而不是从文本节点往上爬 DOM
  const warningRow = screen.getByRole('row', { name: /华夏成长混合/ });
  expect(warningRow).toHaveClass('bg-amber-50/60');
  expect(
    screen.getByRole('checkbox', { name: '选择第 2 行记录' }),
  ).toBeEnabled();
});

test('告警黄标按「页码 + 行号」落行:跨页撞号不再标错行', () => {
  // PDF 每张表的行号都从 1 起,不同页会出现同号行;只比行号会把黄标标到前面页的同号行上
  const result: StatementPreviewResult = {
    ...baseResult,
    summary: { ...baseResult.summary, warnings: 1 },
    preview: [
      makeRow({
        row: 2,
        page: 2,
        fundCode: '000001',
        fundName: '华夏成长混合',
        type: '买入',
      }),
      makeRow({
        row: 2,
        page: 6,
        fundCode: '110011',
        fundName: '易方达中小盘',
        type: '赎回',
      }),
    ],
    warnings: [
      {
        error: '交易类型未能识别，已按申请份额推断为「买入」，请核对',
        row: 2,
        field: 'type',
        page: 6,
      },
    ],
  };
  renderPreview(result);

  const page6Row = screen
    .getAllByRole('row')
    .find((row) => within(row).queryByText(/第 6 页/) !== null);
  const page2Row = screen
    .getAllByRole('row')
    .find((row) => within(row).queryByText(/第 2 页/) !== null);
  expect(page6Row).toHaveClass('bg-amber-50/60');
  expect(page2Row).not.toHaveClass('bg-amber-50/60');
});

test('重新选择文件走 onReset', async () => {
  const user = userEvent.setup();
  const { onReset } = renderPreview();

  await user.click(screen.getByRole('button', { name: '重新选择文件' }));
  expect(onReset).toHaveBeenCalledTimes(1);
});

// 列表式截图(支付宝「交易记录」)特有的展示口径:净值未发布的行只有金额可信,
// 份额与单价必须显示「待确认」而不是 0。
test('列表式截图的待确认行:份额与单价显示「待确认」,金额照常显示', () => {
  renderPreview({
    ...baseResult,
    preview: [
      makeRow({
        row: 3,
        fundCode: '270042',
        fundName: '广发纳斯达克100ETF联接人民币(QDII)A',
        type: '买入',
        amount: 2,
        shares: 0,
        unitPrice: 0,
        navPending: true,
        resolveNote: '全库匹配',
      }),
    ],
    summary: {
      ...baseResult.summary,
      mode: 'listItem',
      parsed: 1,
      total: 1,
      purchases: 1,
      redemptions: 0,
      warnings: 0,
    },
    errors: [],
    warnings: [],
  });

  expect(screen.getAllByText('待确认')).toHaveLength(2);
  expect(screen.getByText('¥2.00')).toBeInTheDocument();
});
