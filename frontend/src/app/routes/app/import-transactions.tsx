// src/app/routes/app/import-transactions.tsx —— 交易导入页
// 单页三步状态机:upload(选文件) → preview(核对并勾选) → result(落库回执)。
// 不跳页:预览与待提交的是同一份内存数据,换路由会让"勾选后确认"多绕一次状态传递;
// 三步只切换主区内容,顶部步骤条给方向感。
// 确认导入后**直接进 result 步**显示处理中进度条(该步此时只有进度条,没有"再导入一份"等入口),
// 请求结束在同一位置换成回执——把"忙"放在"完成"阶段更贴语义(2026-09-22 从 upload 步挪过来)。
// 「是否正在导入」与「本次回执」**不存本地 state**,而是读全局 mutation 缓存(useStatementImportState):
// 切菜单会卸载本组件、本地 state 全丢,而请求仍在后台跑 —— 那样切回来就能再点"选择文件"(2026-09-21 实测踩到)。
// 现在只要请求没结束,任何一次挂载都渲染进度面板(选不了文件);期间跑完,切回来直接是 result 步的回执。
import { useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useState } from 'react';

import {
  STATEMENT_IMPORT_CONFIRM_KEY,
  toConfirmRecords,
  useConfirmStatementImport,
  useDownloadStatementTemplate,
  usePreviewStatementImport,
  useStatementImportState,
  type StatementPreviewResult,
  type StatementPreviewRow,
} from '@/features/statement-import/api/statement-import';
import { StatementConfirmDialog } from '@/features/statement-import/components/statement-confirm-dialog';
import { StatementFilePicker } from '@/features/statement-import/components/statement-file-picker';
import { StatementImportProgress } from '@/features/statement-import/components/statement-import-progress';
import { StatementImportResult } from '@/features/statement-import/components/statement-import-result';
import { StatementPreview } from '@/features/statement-import/components/statement-preview';
import { cn } from '@/utils/cn';

type Step = 'upload' | 'preview' | 'result';

const STEPS: { key: Step; label: string }[] = [
  { key: 'upload', label: '选择文件' },
  { key: 'preview', label: '核对并勾选' },
  { key: 'result', label: '完成' },
];

export default function ImportTransactionsRoute() {
  const [step, setStep] = useState<Step>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<StatementPreviewResult | null>(null);
  // 弹窗确认的那一批:弹窗开着时用户还能取消，所以先把要提交的行存下来
  const [pendingRows, setPendingRows] = useState<StatementPreviewRow[]>([]);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const queryClient = useQueryClient();
  const previewMutation = usePreviewStatementImport();
  const confirmMutation = useConfirmStatementImport();
  // 模板下载与预览/确认无关:只是把后端生成的 xlsx 落盘,页面拿 pending 态禁用按钮
  const downloadTemplate = useDownloadStatementTemplate();
  // 「忙」与「回执」都来自全局 mutation 缓存:切页卸载再回来仍是同一份真相
  const { importing, result, fileName, recordCount } =
    useStatementImportState();
  // 该显示哪一步:处理中与回执都算第三步(完成)——语义上"提交之后"就是完成阶段;
  // 处理中该步只渲染进度条,请求结束原处换成回执(离开期间跑完也一样)
  const activeStep: Step = importing || result ? 'result' : step;
  const reduceMotion = useReducedMotion();
  // 结果步内部还有"处理中→回执"的切换,key 必须区分开才能各自进出场
  const stepKey =
    activeStep === 'result'
      ? importing
        ? 'result-processing'
        : 'result-done'
      : activeStep;

  const handlePreview = () => {
    if (!file || previewMutation.isPending) return;
    previewMutation.mutate(file, {
      onSuccess: (result) => {
        setPreview(result);
        setStep('preview');
      },
    });
  };

  const handleConfirm = () => {
    // 关弹窗即可:处理中由 activeStep 推导到第三步,step 不用改
    // (旧写法 onSettled 才关弹窗,按钮一直转、整页被对话框盖住连菜单都点不动)
    setConfirmOpen(false);
    // 平台作用域(本次预览命中的适配器 key)是判重的依据:不带上后端会直接拒收,不会静默累加重复
    confirmMutation.mutate({
      adapter: preview?.summary.adapter ?? '',
      records: toConfirmRecords(pendingRows),
      fileName: file?.name ?? '',
    });
    // 请求本身失败(超时/网络/5xx)没有回执 → importing 与 result 同时为假,activeStep 落回 step='preview':
    // 预览还在,可直接再点一次确认导入(这条退回路径现在是结构性的,不再需要 onError 回调)
  };

  const handleRestart = () => {
    // 先把已结束的那次导入从缓存移除:否则"再导入一份"会被它的成功回执立刻弹回结果页
    for (const mutation of queryClient.getMutationCache().findAll({
      mutationKey: STATEMENT_IMPORT_CONFIRM_KEY,
      exact: true,
    })) {
      queryClient.getMutationCache().remove(mutation);
    }
    setStep('upload');
    setFile(null);
    setPreview(null);
    setPendingRows([]);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 步骤条:三步各自的产出不同,给一条线索避免用户以为是三个页面 ===== */}
      <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
        {STEPS.map((item, index) => (
          <span key={item.key} className="flex items-center gap-2">
            <span
              className={cn(
                'flex size-5 items-center justify-center rounded-full border text-xs tabular-nums',
                activeStep === item.key &&
                  'border-primary bg-primary text-primary-foreground',
              )}
            >
              {index + 1}
            </span>
            <span className={cn(activeStep === item.key && 'text-foreground')}>
              {item.label}
            </span>
            {index < STEPS.length - 1 ? <span>→</span> : null}
          </span>
        ))}
      </div>

      {/* 三步串行切换:旧内容先退场再让新内容进场(mode=wait),避免两份主区内容重叠 */}
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={stepKey}
          className={
            activeStep === 'upload' ? 'flex flex-col gap-3' : undefined
          }
          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -8 }}
          transition={{ duration: reduceMotion ? 0 : 0.2, ease: 'easeOut' }}
        >
          {activeStep === 'upload' ? (
            <StatementFilePicker
              file={file}
              onSelect={setFile}
              onPreview={handlePreview}
              isParsing={previewMutation.isPending}
              onDownloadTemplate={() => downloadTemplate.mutate()}
              isDownloadingTemplate={downloadTemplate.isPending}
            />
          ) : activeStep === 'preview' && preview ? (
            <StatementPreview
              result={preview}
              onConfirm={(rows) => {
                setPendingRows(rows);
                setConfirmOpen(true);
              }}
              onReset={handleRestart}
            />
          ) : activeStep === 'result' ? (
            importing ? (
              // 处理中只渲染进度条:没有文件选择器、也没有"再导入一份"等入口,
              // 就不会顺手再导一份去撞同一条重建锁。
              // 这份"忙"与文件名/条数都来自全局 mutation 缓存 → 切页回来照样拦住、照样显示完整
              <StatementImportProgress
                fileName={fileName || '本次文件'}
                recordCount={recordCount}
              />
            ) : result ? (
              <StatementImportResult
                result={result}
                onRestart={handleRestart}
              />
            ) : null
          ) : null}
        </motion.div>
      </AnimatePresence>

      {/* 二次确认:按平台累加(同平台重复跳过),随后全量重建持仓与快照 */}
      <StatementConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`确认导入 ${pendingRows.length} 条记录？`}
        description={`按「${preview?.summary.adapterName ?? '当前平台'}」累加：与本平台已导入记录重复的会自动跳过，其它平台与手工录入的记录一律保留；导入后持仓与历史持仓会按新流水重建。`}
        confirmText="确认导入"
        onConfirm={handleConfirm}
      />
    </div>
  );
}
