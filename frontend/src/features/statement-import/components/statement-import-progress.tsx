// src/features/statement-import/components/statement-import-progress.tsx —— 导入进行中(点完二次确认之后)
// 进度不可知:后端在同一个请求里做完「写入记录 + 重建快照」,前端看不到那条分界线,所以只给"进行中"
// 的信号、不假装百分比(不确定进度条见 index.css 的 --animate-indeterminate)。
// 它顶掉「选择文件」的位置渲染:处理期间没有选择入口,就不会顺手再导一份去撞重建锁。
// 两个 props 来自 mutation 变量(不是本页 state),所以切菜单再回来仍显示得出来。
type StatementImportProgressProps = {
  fileName: string;
  recordCount: number;
};

export function StatementImportProgress({
  fileName,
  recordCount,
}: StatementImportProgressProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col gap-4 rounded-xl border border-dashed p-6"
    >
      <div className="flex flex-col gap-1">
        <p className="font-heading text-sm font-medium">
          正在导入并重建历史持仓…
        </p>
        <p className="text-muted-foreground text-sm">
          {fileName} · {recordCount} 条记录。期间无法选择下一个文件，请稍候。
        </p>
      </div>
      <div className="relative h-1 w-full overflow-hidden rounded-full bg-muted">
        <div className="animate-indeterminate absolute inset-y-0 w-1/3 rounded-full bg-primary motion-reduce:w-full motion-reduce:animate-pulse" />
      </div>
    </div>
  );
}
