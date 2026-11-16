// 可排序表头单测:钉「点击语义」「三态图标」与「必须经列对象调用」。
//
// 排序本身是服务端做的(持仓页),组件只把点击翻译成 tanstack 的 toggleSorting(desc?)。
// 假列**故意写成原型风格(方法读 this)**,与真实 v9 列一致:一旦实现把方法解构出来调用,
// this 丢失就会抛错 → 这条用例立刻变红。2026-09-22 线上崩过一次
// (column_getIsSorted 读 this.table 报 undefined),当时假列是箭头函数、不读 this,才漏了。
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import {
  DataTableColumnHeader,
  SortableHeaderButton,
} from '@/components/shared/data-table-column-header';

type FakeColumn = {
  sorted: false | 'asc' | 'desc';
  toggledWith: boolean[];
  getIsSorted(this: FakeColumn): false | 'asc' | 'desc';
  toggleSorting(this: FakeColumn, desc?: boolean): void;
};

const makeColumn = (sorted: false | 'asc' | 'desc'): FakeColumn => ({
  sorted,
  toggledWith: [],
  getIsSorted() {
    return this.sorted;
  },
  toggleSorting(desc) {
    this.toggledWith.push(desc === true);
  },
});

/** 渲染一个指定排序态的表头,把假列交回调用方断言 */
const renderHeader = (column: FakeColumn) => {
  render(
    <DataTableColumnHeader
      column={column as never}
      title="当前市值"
      align="right"
    />,
  );
};

test('未排序时点击 → 首次按降序(金额列先看大的)', async () => {
  const user = userEvent.setup();
  const column = makeColumn(false);
  renderHeader(column);

  await user.click(screen.getByRole('button', { name: /当前市值/ }));

  expect(column.toggledWith).toEqual([false]);
});

test('已升序时点击 → 切降序', async () => {
  const user = userEvent.setup();
  const column = makeColumn('asc');
  renderHeader(column);

  await user.click(screen.getByRole('button', { name: /当前市值/ }));

  expect(column.toggledWith).toEqual([true]);
});

test('图标随排序状态切换:未排序双箭头 / 升序 / 降序', () => {
  renderHeader(makeColumn(false));
  expect(screen.getByTestId('sort-icon-none')).toBeInTheDocument();

  renderHeader(makeColumn('asc'));
  expect(screen.getByTestId('sort-icon-asc')).toBeInTheDocument();

  renderHeader(makeColumn('desc'));
  expect(screen.getByTestId('sort-icon-desc')).toBeInTheDocument();
});

test('v9 列方法不可解构:摘成裸函数调用会因丢 this 而崩(回归保护)', () => {
  const column = makeColumn(false);
  // 组件必须经列对象调用;下面这条「反例」就是线上崩过的那种写法
  const { getIsSorted } = column;
  expect(() => (getIsSorted as () => unknown)()).toThrow(TypeError);
  // 经列对象调用则正常 —— 组件走的正是这条路
  expect(column.getIsSorted()).toBe(false);
});

test('toggleSorting 同样依赖 this:解构调用不会记到列上', () => {
  const column = makeColumn(false);
  const { toggleSorting } = column;
  expect(() => (toggleSorting as (desc?: boolean) => void)(false)).toThrow(
    TypeError,
  );
  expect(column.toggledWith).toEqual([]);
});

test('底层 SortableHeaderButton:与 tanstack 解耦,三态图标 + 点击回调(简况页这类纯表格复用)', async () => {
  const user = userEvent.setup();
  const onToggle = vi.fn();
  render(
    <SortableHeaderButton
      title="市值"
      align="center"
      direction={false}
      onToggle={onToggle}
    />,
  );

  expect(screen.getByTestId('sort-icon-none')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /市值/ }));

  expect(onToggle).toHaveBeenCalledTimes(1);
});

test('底层 SortableHeaderButton:已排序时显示单向箭头', () => {
  const { rerender } = render(
    <SortableHeaderButton title="市值" direction="asc" onToggle={vi.fn()} />,
  );
  expect(screen.getByTestId('sort-icon-asc')).toBeInTheDocument();

  rerender(
    <SortableHeaderButton title="市值" direction="desc" onToggle={vi.fn()} />,
  );
  expect(screen.getByTestId('sort-icon-desc')).toBeInTheDocument();
});
