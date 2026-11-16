// 导入第一步的单测:空态 → 文件卡片的两态切换、拖拽落文件、.xls 软提示、解析中的 pending 态
// 断言的是一条产品规则——「后端按内容识别类型,所以前端只提示不拦」:除了 .xls 给出"另存为"指引,
// 其他扩展名一律放行到解析阶段。
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import { StatementFilePicker } from '@/features/statement-import/components/statement-file-picker';

function Harness({
  isParsing = false,
  isDownloadingTemplate = false,
  onDownloadTemplate = vi.fn(),
}: {
  isParsing?: boolean;
  isDownloadingTemplate?: boolean;
  onDownloadTemplate?: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const onPreview = vi.fn();
  return (
    <>
      <StatementFilePicker
        file={file}
        onSelect={setFile}
        onPreview={onPreview}
        isParsing={isParsing}
        onDownloadTemplate={onDownloadTemplate}
        isDownloadingTemplate={isDownloadingTemplate}
      />
      <button type="button" onClick={onPreview}>
        外部触发解析
      </button>
    </>
  );
}

const makeFile = (name: string, bytes = 2048) =>
  new File(['x'.repeat(bytes)], name, { type: '' });

// 隐藏 input 用 aria-label 定位:input 无可见 label,setter 走 props 回调
const fileInput = () =>
  screen.getByLabelText('选择交易明细文件') as HTMLInputElement;

test('未选文件时是可拖拽的虚线空态', () => {
  render(<Harness />);

  expect(screen.getByText('还没有选择文件')).toBeInTheDocument();
  // 空态整块是拖拽区,「选择文件」是区内真实按钮(不是 div 模拟)
  expect(screen.getByRole('button', { name: '选择文件' })).toBeEnabled();
  expect(
    screen.queryByRole('button', { name: '解析并预览' }),
  ).not.toBeInTheDocument();
});

test('空态说明写清支持的平台与文件类型', () => {
  render(<Harness />);

  // 使用者得先知道"能导哪些平台",否则会导到一半才发现不支持
  const description = screen.getByText(/目前支持支付宝、天天基金导出的文件/);
  expect(description).toHaveTextContent('Excel 明细');
  expect(description).toHaveTextContent('按文件内容识别类型、不看扩展名');
  // 没有对账单的用户得有出路:模板入口的文案要在
  expect(description).toHaveTextContent('也可以点「下载模板」按模板自行填写');
});

test('选中文件后空态换成文件卡片,并显示类型与体积', async () => {
  const user = userEvent.setup();
  render(<Harness />);

  await user.upload(fileInput(), makeFile('alipay-2026.xlsx'));

  expect(screen.queryByText('还没有选择文件')).not.toBeInTheDocument();
  expect(screen.getByText('alipay-2026.xlsx')).toBeInTheDocument();
  expect(screen.getByText('Excel 明细 · 2.0 KB')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '解析并预览' })).toBeEnabled();
});

test('拖拽落文件与点选等价', async () => {
  render(<Harness />);

  fireEvent.drop(screen.getByText('还没有选择文件'), {
    dataTransfer: { files: [makeFile('statement.pdf')] },
  });

  expect(screen.getByText('statement.pdf')).toBeInTheDocument();
  expect(screen.getByText('PDF 对账单 · 2.0 KB')).toBeInTheDocument();
});

test('.xls 走拖拽时给"另存为"软提示但不阻断解析按钮', async () => {
  render(<Harness />);

  // 用拖拽而不是上传:input 的 accept 会让系统文件框过滤掉 .xls(用户根本选不到),
  // 真正能碰到 .xls 的路径就是拖拽 —— 这正是这条软提示存在的理由。
  fireEvent.drop(screen.getByText('还没有选择文件'), {
    dataTransfer: { files: [makeFile('old-export.xls')] },
  });

  expect(
    screen.getByText('Excel 97-2003 的 .xls 无法解析，请另存为 .xlsx 后重试'),
  ).toBeInTheDocument();
  // 只提示不拦:后端按魔数判定,内容其实是 xlsx 的 .xls 仍可能解析成功
  expect(screen.getByRole('button', { name: '解析并预览' })).toBeEnabled();
});

test('解析中:卡片显示"正在解析…"且按钮禁用', async () => {
  const user = userEvent.setup();
  const { rerender } = render(<Harness />);

  await user.upload(fileInput(), makeFile('alipay.xlsx'));
  rerender(<Harness isParsing />);

  expect(screen.getByText('正在解析…')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /解析并预览/ })).toBeDisabled();
});

test('空态并列提供"下载模板"入口,点击即触发下载', async () => {
  const user = userEvent.setup();
  const onDownloadTemplate = vi.fn();
  render(<Harness onDownloadTemplate={onDownloadTemplate} />);

  await user.click(screen.getByRole('button', { name: '下载模板' }));

  expect(onDownloadTemplate).toHaveBeenCalledTimes(1);
});

test('模板下载中:按钮禁用(避免重复点)', () => {
  render(<Harness isDownloadingTemplate />);

  expect(screen.getByRole('button', { name: /下载模板/ })).toBeDisabled();
});
