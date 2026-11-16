// src/components/shared/date-field.tsx —— 日历选择字段(Popover + Calendar 单选)
// value 固定为 'yyyy-MM-dd' 字符串:与后端日期参数的契约一致,调用方无需再做格式转换;
// 自带的清除按钮是原生 date 输入的能力补位(日历形态本身删不掉已选日期)
// 其余 props(含 FormControl 注入的 id/aria-*/ref)一律透到 trigger:表单里靠它关联 label 与错误态
import { format } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { CalendarIcon, XIcon } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/utils/cn';

type DateFieldProps = Omit<
  React.ComponentProps<typeof Button>,
  'value' | 'onChange'
> & {
  /** 'yyyy-MM-dd',空串表示未选择 */
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
};

export function DateField({
  value,
  onChange,
  placeholder,
  className,
  ...triggerProps
}: DateFieldProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className={cn('w-36 justify-start font-normal', className)}
            aria-label={placeholder}
            // 透传放最后:调用方传的 size/className/id 覆盖默认值;
            // 表单里不写 id 时,FormControl(Radix Slot)注入的 formItemId 就落在这里,
            // FormLabel 的 htmlFor 与 aria-invalid 描红才生效
            {...triggerProps}
          >
            <CalendarIcon className="text-muted-foreground" />
            {value ? (
              <span>{value}</span>
            ) : (
              <span className="text-muted-foreground">{placeholder}</span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            mode="single"
            captionLayout="dropdown"
            locale={zhCN}
            selected={value ? new Date(`${value}T00:00:00`) : undefined}
            onSelect={(day) => {
              if (!day) return;
              onChange(format(day, 'yyyy-MM-dd'));
              setOpen(false);
            }}
          />
        </PopoverContent>
      </Popover>
      {/* 清除按钮(叠加在 trigger 右侧;原生 date 输入可删文本,日历形态补等价能力) */}
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          className="text-muted-foreground hover:text-foreground absolute top-1/2 right-1.5 -translate-y-1/2 rounded-sm p-0.5"
          aria-label={`清除${placeholder}`}
        >
          <XIcon className="size-3.5" />
        </button>
      )}
    </div>
  );
}
