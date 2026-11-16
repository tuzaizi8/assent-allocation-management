// src/features/statement-import/components/statement-preview.tsx —— 导入第二步:核对与勾选
// 默认全选可提交行(用户多数情况下就是要全导),但要能逐行取消 → 提交时只发勾选行;
// 分页是本地切片:preview 是一次性内存列表,没有服务端分页,复用公共分页条只为形态一致。
import {
  CreditCardMinusIcon,
  CreditCardPlusIcon,
  FileInputIcon,
  FilesIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  ImageIcon,
  LandmarkIcon,
  ReplaceIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from 'lucide-react';
import { useMemo, useState } from 'react';

import { DataTablePagination } from '@/components/shared/data-table-pagination';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type {
  StatementPreviewResult,
  StatementPreviewRow,
} from '@/features/statement-import/api/statement-import';
import { StatementIssueList } from '@/features/statement-import/components/statement-issue-list';
import { StatementPreviewTable } from '@/features/statement-import/components/statement-preview-table';

const KIND_LABEL: Record<StatementPreviewResult['summary']['kind'], string> = {
  excel: 'Excel 明细',
  pdf: 'PDF 对账单',
  image: '图片截图',
};

// 文件类型徽标的图标:三种 kind 天然一一对应,与 KIND_LABEL 同键
const KIND_ICON: Record<StatementPreviewResult['summary']['kind'], LucideIcon> =
  {
    excel: FileSpreadsheetIcon,
    pdf: FileTextIcon,
    image: ImageIcon,
  };

const PAGE_SIZE = 20;

type StatementPreviewProps = {
  result: StatementPreviewResult;
  onConfirm: (rows: StatementPreviewRow[]) => void;
  onReset: () => void;
};

export function StatementPreview({
  result,
  onConfirm,
  onReset,
}: StatementPreviewProps) {
  const { preview, summary, errors, warnings } = result;
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  // 默认全选:可提交行就是 preview 的全部(错误行后端已剔除,不在这份数据里)
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(preview.map((_, index) => index)),
  );
  // useState 初值只在挂载时求一次:换了预览结果必须重置勾选,否则残留上一份文件的下标
  const [selectionSource, setSelectionSource] = useState(result);
  if (selectionSource !== result) {
    setSelectionSource(result);
    setSelected(new Set(result.preview.map((_, index) => index)));
  }

  // 下标 → 告警原因:告警带「行号 + 页码」,先建「(页码, 行号) → 下标」索引再回填。
  // 必须连页码一起比:一张 PDF 里每张表的行号都从 1 起,跨表/跨页必撞号——
  // 只比行号会把黄标标到**前面某一页**的同号行上(78 页蚂蚁明细实测:第 6 页 14 行的告警
  // 标到了第 2 页 2 行…同号的另一行),问题清单里的行号页码是对的、表格黄标却是错的。
  const warningsByIndex = useMemo(() => {
    const indexByKey = new Map<string, number>();
    preview.forEach((row, index) => {
      if (row.row != null) {
        const key = `${row.page ?? null}:${row.row}`;
        if (!indexByKey.has(key)) {
          indexByKey.set(key, index);
        }
      }
    });
    const map = new Map<number, string[]>();
    warnings.forEach((issue) => {
      if (issue.row == null) return;
      const index = indexByKey.get(`${issue.page ?? null}:${issue.row}`);
      if (index === undefined) return;
      map.set(index, [...(map.get(index) ?? []), issue.error]);
    });
    return map;
  }, [preview, warnings]);

  const totalPages = Math.max(1, Math.ceil(preview.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageRows = preview.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );

  const selectedRows = preview.filter((_, index) => selected.has(index));
  // 表头勾选看**当前页**而不是全表:表头的 aria-label 承诺的是「本页」,
  // 若用全表口径,多页时会出现"本页已全选但表头半选、点它又无反应"的死角。
  const pageIndexes = pageRows.map(
    (_, offset) => (currentPage - 1) * pageSize + offset,
  );
  const selectedOnPage = pageIndexes.filter((index) =>
    selected.has(index),
  ).length;
  const headerChecked: boolean | 'indeterminate' =
    selectedOnPage === 0
      ? false
      : selectedOnPage === pageRows.length
        ? true
        : 'indeterminate';

  const toggleRow = (index: number) =>
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  const togglePage = (checked: boolean) =>
    setSelected((previous) => {
      const next = new Set(previous);
      pageRows.forEach((_, offset) => {
        const index = (currentPage - 1) * pageSize + offset;
        if (checked) next.add(index);
        else next.delete(index);
      });
      return next;
    });

  const KindIcon = KIND_ICON[summary.kind];

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 统计:先给"解析出了什么"的整体印象,再往下看细节 ===== */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="解析记录" value={summary.parsed} icon={FilesIcon} />
        <StatCard
          title="买入"
          value={summary.purchases}
          icon={CreditCardPlusIcon}
        />
        <StatCard
          title="赎回"
          value={summary.redemptions}
          icon={CreditCardMinusIcon}
        />
        <StatCard
          title="告警"
          value={summary.warnings}
          icon={TriangleAlertIcon}
          tone={summary.warnings > 0 ? 'warning' : undefined}
        />
      </div>

      {/* 只答"哪个平台的什么文件":抽取模式与平均置信度是内部概念,使用者要看的是数据对不对 */}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="secondary">
          <LandmarkIcon />
          {summary.adapterName}
        </Badge>
        <Badge variant="outline">
          <KindIcon />
          {KIND_LABEL[summary.kind]}
        </Badge>
      </div>

      <StatementIssueList errors={errors} warnings={warnings} />

      {/* ===== 待提交表:标题与两个动作同一行(照系统管理页的工具栏范式) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-heading text-base leading-snug font-medium">
          待提交记录
        </p>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={onReset}>
            <ReplaceIcon />
            重新选择文件
          </Button>
          <Button
            size="sm"
            disabled={selectedRows.length === 0}
            onClick={() => onConfirm(selectedRows)}
          >
            <FileInputIcon />
            确认导入 {selectedRows.length} 条
          </Button>
        </div>
      </div>

      {/* 表格自带 overflow-x-auto rounded-lg border 容器,故此处不再套 Card */}
      <StatementPreviewTable
        rows={pageRows}
        rowOffset={(currentPage - 1) * pageSize}
        isSelected={(index) => selected.has(index)}
        warningsByIndex={warningsByIndex}
        onToggleRow={toggleRow}
        onToggleAll={togglePage}
        headerChecked={headerChecked}
      />

      <DataTablePagination
        meta={{
          currentPage,
          totalPages,
          totalItems: preview.length,
          itemCount: pageRows.length,
          itemsPerPage: pageSize,
        }}
        page={currentPage}
        pageSize={pageSize}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size);
          setPage(1);
        }}
        leftLabel={`已选 ${selectedRows.length} / ${preview.length} 条`}
        idPrefix="statement-preview-rows"
      />
    </div>
  );
}

function StatCard({
  title,
  value,
  icon: Icon,
  tone,
}: {
  title: string;
  value: number;
  /** 右上角装饰图标:照仪表盘卡片的浮层范式(right-4 top-4 + 灰 + size-5) */
  icon: LucideIcon;
  tone?: 'warning';
}) {
  return (
    <Card className="relative gap-1 py-4">
      <Icon className="text-muted-foreground absolute right-4 top-4 size-5" />
      <CardContent className="px-4">
        <p className="text-muted-foreground text-sm">{title}</p>
        <p
          className={
            tone === 'warning'
              ? 'text-2xl font-semibold tabular-nums text-amber-600'
              : 'text-2xl font-semibold tabular-nums'
          }
        >
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
