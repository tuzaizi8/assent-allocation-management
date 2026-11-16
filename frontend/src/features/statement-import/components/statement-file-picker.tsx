// src/features/statement-import/components/statement-file-picker.tsx —— 导入第一步:选文件
// 两个形态同区切换:未选文件是虚线空态(可拖拽落文件),选中后换成文件卡片(可移除、可解析)。
// 选文件不自动发请求:preview 限流 12 次/120 秒,连点会烧配额,解析必须由用户显式点按钮触发。
import {
  DownloadIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  ImageIcon,
  ReplaceIcon,
  ScanSearchIcon,
  UploadIcon,
  XIcon,
} from 'lucide-react';
import { useRef, useState } from 'react';

import {
  Attachment,
  AttachmentAction,
  AttachmentActions,
  AttachmentContent,
  AttachmentDescription,
  AttachmentMedia,
  AttachmentTitle,
} from '@/components/ui/attachment';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import { Spinner } from '@/components/ui/spinner';
import {
  describeFileNotice,
  STATEMENT_IMPORT_ACCEPT,
} from '@/features/statement-import/api/statement-import';
import { cn } from '@/utils/cn';
import { formatFileSize } from '@/utils/format';

type StatementFilePickerProps = {
  file: File | null;
  onSelect: (file: File | null) => void;
  onPreview: () => void;
  isParsing: boolean;
  /** 下载导入模板(模板由后端生成,表头与解析器同源) */
  onDownloadTemplate: () => void;
  isDownloadingTemplate: boolean;
};

/** 文件图标按扩展名给:仅影响观感,真正认类型的是后端的魔数嗅探 */
const resolveFileIcon = (name: string) => {
  const extension = name.split('.').pop()?.toLowerCase() ?? '';
  if (extension === 'pdf') return FileTextIcon;
  if (extension === 'png' || extension === 'jpg' || extension === 'jpeg')
    return ImageIcon;
  return FileSpreadsheetIcon;
};

const resolveTypeLabel = (name: string) => {
  const extension = name.split('.').pop()?.toLowerCase() ?? '';
  const labels: Record<string, string> = {
    xlsx: 'Excel 明细',
    xls: 'Excel 97-2003',
    pdf: 'PDF 对账单',
    png: 'PNG 截图',
    jpg: 'JPEG 截图',
    jpeg: 'JPEG 截图',
  };
  return labels[extension] ?? '未知类型';
};

export function StatementFilePicker({
  file,
  onSelect,
  onPreview,
  isParsing,
  onDownloadTemplate,
  isDownloadingTemplate,
}: StatementFilePickerProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);

  const notice = file ? describeFileNotice(file) : null;

  const handleFiles = (files: FileList | null) => {
    const picked = files?.[0];
    if (picked) onSelect(picked);
  };

  return (
    <div className="flex flex-col gap-3">
      <input
        ref={inputRef}
        type="file"
        accept={STATEMENT_IMPORT_ACCEPT}
        aria-label="选择交易明细文件"
        className="hidden"
        onChange={(event) => {
          handleFiles(event.target.files);
          // 清空 value:同一文件再次选择也要触发 change
          event.target.value = '';
        }}
      />

      {!file ? (
        // 拖拽区承载落文件,「选择文件」是区内真实按钮 → 键盘与鼠标都可达,不用 div 冒充按钮
        <Empty
          className={cn(
            'border border-dashed transition-colors',
            dragActive && 'border-primary bg-muted/50',
          )}
          onDragOver={(event) => {
            event.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragActive(false);
            handleFiles(event.dataTransfer.files);
          }}
        >
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <UploadIcon />
            </EmptyMedia>
            <EmptyTitle>还没有选择文件</EmptyTitle>
            <EmptyDescription>
              目前支持支付宝、天天基金导出的文件：Excel 明细、PDF
              对账单、手机截图均可，按文件内容识别类型、不看扩展名。也可以点「下载模板」按模板自行填写，或把文件拖到这里。
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            {/* 两条入口并列:有对账单的直接选文件,没有的按模板自己填 */}
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={() => inputRef.current?.click()}>
                选择文件
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={isDownloadingTemplate}
                onClick={onDownloadTemplate}
              >
                {isDownloadingTemplate ? <Spinner /> : <DownloadIcon />}
                下载模板
              </Button>
            </div>
          </EmptyContent>
        </Empty>
      ) : (
        <div className="flex flex-col gap-3">
          <Attachment
            className="w-full"
            state={isParsing ? 'uploading' : 'done'}
          >
            <AttachmentMedia>
              {isParsing ? <Spinner /> : <FileIcon name={file.name} />}
            </AttachmentMedia>
            <AttachmentContent>
              <AttachmentTitle>{file.name}</AttachmentTitle>
              <AttachmentDescription>
                {isParsing
                  ? '正在解析…'
                  : `${resolveTypeLabel(file.name)} · ${formatFileSize(file.size)}`}
              </AttachmentDescription>
            </AttachmentContent>
            <AttachmentActions>
              <AttachmentAction
                aria-label={`移除 ${file.name}`}
                disabled={isParsing}
                onClick={() => onSelect(null)}
              >
                <XIcon />
              </AttachmentAction>
            </AttachmentActions>
          </Attachment>

          {/* 软提示:后端按魔数判定,提示只影响预期管理,不拦提交 */}
          {notice ? (
            <p
              className={cn(
                'text-sm',
                notice.level === 'warning'
                  ? 'text-amber-600'
                  : 'text-muted-foreground',
              )}
            >
              {notice.message}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={isParsing}
              onClick={() => onSelect(null)}
            >
              <ReplaceIcon />
              换一个文件
            </Button>
            <Button size="sm" disabled={isParsing} onClick={onPreview}>
              {isParsing ? <Spinner /> : <ScanSearchIcon />}
              解析并预览
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function FileIcon({ name }: { name: string }) {
  const Icon = resolveFileIcon(name);
  return <Icon />;
}
