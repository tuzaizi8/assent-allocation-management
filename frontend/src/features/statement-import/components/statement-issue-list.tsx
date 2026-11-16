// src/features/statement-import/components/statement-issue-list.tsx —— 解析结果的守恒校验问题
// 错误(error)与告警(warning)分级展示:错误行后端已从 preview 里剔除、永远不会被提交,
// 这里是唯一能看到它们的地方 → 给一张只读表(不放勾选框:没有可勾的东西)。
// 告警只提示不拦:对应记录仍在待提交表里,由用户决定是否勾选——同样用表格展示,只是换琥珀色。
// "这是什么/该怎么办"两段说明挂在各自标题左侧的图标上(悬停或 Tab 聚焦显示),正文只留标题+表格。
// 图标必须保持 Alert 的直接子元素(图标槽靠 has-[>svg]/*:[svg] 定位),故 Tooltip 一律用 asChild——加包裹层会立即错位。
import {
  ChevronDownIcon,
  ChevronUpIcon,
  CircleAlertIcon,
  TriangleAlertIcon,
} from 'lucide-react';
import { useState } from 'react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { StatementIssue } from '@/features/statement-import/api/statement-import';
import { cn } from '@/utils/cn';

const COLLAPSED_COUNT = 5;

// 两类问题共用同一张表,只差色调:错误=不能提交(destructive),告警=可以提交但要看一眼(amber)
const ISSUE_TONE = {
  error: { row: 'bg-destructive/5', reason: 'text-destructive' },
  warning: { row: 'bg-amber-50/60', reason: 'text-amber-600' },
} as const;

type StatementIssueListProps = {
  errors: StatementIssue[];
  warnings: StatementIssue[];
};

/** 来源定位:`第 N 页 / 第 N 行`(Excel 行号、PDF 表内行序、OCR 网格行序都落在 row 上) */
const describeLocation = (issue: StatementIssue) =>
  [
    issue.row == null ? null : `第 ${issue.row} 行`,
    issue.page == null ? null : `第 ${issue.page} 页`,
  ]
    .filter(Boolean)
    .join(' · ') || '来源未知';

export function StatementIssueList({
  errors,
  warnings,
}: StatementIssueListProps) {
  const [errorsExpanded, setErrorsExpanded] = useState(false);
  const [warningsExpanded, setWarningsExpanded] = useState(false);

  if (errors.length === 0 && warnings.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      {errors.length > 0 ? (
        <Alert variant="destructive">
          <Tooltip>
            <TooltipTrigger asChild>
              <CircleAlertIcon />
            </TooltipTrigger>
            <TooltipContent>
              这些行的数据本身不成立（代码位数、日期、份额或金额对不上），请回到原文件修正后重新上传。
            </TooltipContent>
          </Tooltip>
          <AlertTitle>
            有 {errors.length} 条记录没有通过校验，不会被提交
          </AlertTitle>
          <AlertDescription>
            <IssueTable
              issues={errors}
              tone="error"
              expanded={errorsExpanded}
              onToggle={() => setErrorsExpanded((value) => !value)}
            />
          </AlertDescription>
        </Alert>
      ) : null}

      {warnings.length > 0 ? (
        <Alert>
          {/* 图标改色用 stroke- 而非 text-:Alert 容器的 *:[svg]:text-current 优先级(0,1,1)
              会压掉普通 text-*(0,1,0);而 Alert 只设 color、不设 stroke,
              直接用 stroke-amber-600 改描边色即可(无需 !important)。 */}
          <Tooltip>
            <TooltipTrigger asChild>
              <TriangleAlertIcon className="stroke-amber-600" />
            </TooltipTrigger>
            <TooltipContent>
              多为手续费与四舍五入的口径差，或净值为 0 时按「金额 ÷
              份额」兜底；确认无误即可提交。
            </TooltipContent>
          </Tooltip>
          <AlertTitle className="text-amber-600">
            有 {warnings.length} 条记录带提示，可以提交
          </AlertTitle>
          <AlertDescription>
            <IssueTable
              issues={warnings}
              tone="warning"
              expanded={warningsExpanded}
              onToggle={() => setWarningsExpanded((value) => !value)}
            />
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

/** 问题行只读表:只答「哪一行、哪个字段、为什么」,不放勾选框(这批行要么不可提交、要么已在待提交表里勾选) */
function IssueTable({
  issues,
  tone,
  expanded,
  onToggle,
}: {
  issues: StatementIssue[];
  tone: keyof typeof ISSUE_TONE;
  expanded: boolean;
  onToggle: () => void;
}) {
  const visible = expanded ? issues : issues.slice(0, COLLAPSED_COUNT);

  return (
    <div className="flex flex-col gap-2">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-36">来源</TableHead>
            <TableHead className="w-28">字段</TableHead>
            <TableHead>原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.map((issue, index) => (
            <TableRow
              key={`${issue.row}-${issue.field}-${index}`}
              className={cn(
                ISSUE_TONE[tone].row,
                // 展开全部时新增行依次出现,原有 5 行 key 不变、不会重播
                'animate-in fade-in-0 fill-mode-both duration-150 motion-reduce:animate-none',
              )}
              style={{ animationDelay: `${Math.min(index, 8) * 20}ms` }}
            >
              <TableCell className="text-muted-foreground text-sm tabular-nums">
                {describeLocation(issue)}
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {issue.field}
              </TableCell>
              <TableCell className={`text-sm ${ISSUE_TONE[tone].reason}`}>
                {issue.error}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {issues.length > COLLAPSED_COUNT ? (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 self-start px-2 text-xs"
          onClick={onToggle}
        >
          {expanded ? <ChevronUpIcon /> : <ChevronDownIcon />}
          {expanded ? '收起' : `展开全部 ${issues.length} 条`}
        </Button>
      ) : null}
    </div>
  );
}
