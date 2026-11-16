// src/features/statement-import/components/statement-import-result.tsx —— 导入第三步:落库回执
// 成功位读的是内层 data.success:外层信封恒 true(用户取消与落库前校验拦截都走 success=false)。
// 这一步只做陈述与下一步导航,不做任何写操作。
import {
  ArrowRightIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  FilePlusIcon,
} from 'lucide-react';
import { useReducedMotion } from 'motion/react';
import { Link } from 'react-router';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { paths } from '@/config/paths';
import type { StatementConfirmResult } from '@/features/statement-import/api/statement-import';
import { useCountUp } from '@/hooks/use-count-up';

type StatementImportResultProps = {
  result: StatementConfirmResult;
  onRestart: () => void;
};

export function StatementImportResult({
  result,
  onRestart,
}: StatementImportResultProps) {
  const imported = result.imported as {
    purchases?: number;
    redemptions?: number;
  };
  const purchases = imported.purchases ?? 0;
  const redemptions = imported.redemptions ?? 0;
  const positionsCreated = result.positionsCreated ?? 0;
  // 回执三个计数滚动出现:导入完成后数字从 0 落到实际值,比静态文案更像"结算完成"
  const reduceMotion = useReducedMotion();
  const countOptions = { enabled: !reduceMotion };
  const purchasesDisplay = useCountUp(purchases, countOptions);
  const redemptionsDisplay = useCountUp(redemptions, countOptions);
  const positionsDisplay = useCountUp(positionsCreated, countOptions);
  const shown = (value: number | null) => Math.round(value ?? 0);

  return (
    <div className="flex flex-col gap-4">
      {result.success ? (
        <Alert>
          <CircleCheckIcon className="text-emerald-600" />
          <AlertTitle className="text-emerald-600">导入完成</AlertTitle>
          <AlertDescription>
            写入买入 {shown(purchasesDisplay)} 条、赎回{' '}
            {shown(redemptionsDisplay)} 条，新建持仓 {shown(positionsDisplay)}{' '}
            个；持仓与快照已按新流水重建，可直接去持仓明细或快照管理核对。
          </AlertDescription>
        </Alert>
      ) : (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>导入未完成</AlertTitle>
          <AlertDescription>
            {result.errors[0]?.error ??
              '后端拒绝了这次提交（可能含未通过校验的记录），本次没有写入任何数据。'}
          </AlertDescription>
        </Alert>
      )}

      {result.errors.length > 0 && result.success ? (
        <Card className="gap-3 py-4">
          <CardHeader className="px-4">
            <CardTitle className="text-base">
              跳过或失败的记录（{result.errors.length} 条）
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4">
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-32">基金代码</TableHead>
                    <TableHead>原因</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.errors.map((issue, index) => (
                    <TableRow
                      key={index}
                      className="animate-in fade-in-0 fill-mode-both duration-150 motion-reduce:animate-none"
                      style={{
                        animationDelay: `${Math.min(index, 8) * 20}ms`,
                      }}
                    >
                      <TableCell className="tabular-nums">
                        {issue.fund_code ?? '—'}
                      </TableCell>
                      <TableCell className="text-destructive text-sm">
                        {issue.error}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={onRestart}>
          <FilePlusIcon />
          再导入一份
        </Button>
        <Button variant="ghost" size="sm" asChild>
          <Link to={paths.app.asset.positions.getHref()}>
            查看持仓明细
            <ArrowRightIcon />
          </Link>
        </Button>
        <Button variant="ghost" size="sm" asChild>
          <Link to={paths.app.asset.snapshots.getHref()}>
            查看快照管理
            <ArrowRightIcon />
          </Link>
        </Button>
      </div>
    </div>
  );
}
