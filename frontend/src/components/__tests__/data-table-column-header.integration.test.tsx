// 集成用例:把排序表头装进**真实的 tanstack 表格**(与持仓页同样的 rowSortingFeature),
// 复现线上崩过的那个场景——组件若把列方法解构出来调用(丢 this),这里会立刻抛
// 「Cannot read properties of undefined (reading 'table')」。单测里的假列测不到这一点。
import type { SortingState } from '@tanstack/react-table';
import {
  flexRender,
  rowSortingFeature,
  tableFeatures,
  useTable,
} from '@tanstack/react-table';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DataTableColumnHeader } from '@/components/shared/data-table-column-header';

const FEATURES = tableFeatures({ rowSortingFeature });
const INITIAL_SORTING: SortingState = [{ id: 'value', desc: true }];

function MiniTable({
  onSortingChange,
}: {
  onSortingChange: (next: SortingState) => void;
}) {
  const table = useTable({
    features: FEATURES,
    data: [{ value: 1 }],
    columns: [
      {
        accessorKey: 'value',
        header: ({ column }: { column: never }) => (
          <DataTableColumnHeader
            column={column}
            title="当前市值"
            align="right"
          />
        ),
      },
    ],
    state: { sorting: INITIAL_SORTING },
    onSortingChange: (
      updater: SortingState | ((prev: SortingState) => SortingState),
    ) => {
      const next =
        typeof updater === 'function' ? updater(INITIAL_SORTING) : updater;
      onSortingChange(next);
    },
    // v9 的 options 交叉类型在泛型未定时无法从字面量满足,收窄一次(与 useDataTable 同款做法)
  } as never);
  const header = table.getHeaderGroups()[0].headers[0];
  return (
    <table>
      <thead>
        <tr>
          <th>
            {flexRender(header.column.columnDef.header, header.getContext())}
          </th>
        </tr>
      </thead>
    </table>
  );
}

test('与真实表格装配:渲染不崩,点击把排序切到升序', async () => {
  const user = userEvent.setup();
  const changes: SortingState[] = [];
  render(<MiniTable onSortingChange={(next) => changes.push(next)} />);

  // 初始降序 → 图标是单向降序箭头;点击一次(已降序)应转升序
  expect(screen.getByTestId('sort-icon-desc')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /当前市值/ }));

  expect(changes).toEqual([[{ id: 'value', desc: false }]]);
});
