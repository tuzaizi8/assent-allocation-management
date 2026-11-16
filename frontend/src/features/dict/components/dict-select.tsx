// src/features/dict/components/dict-select.tsx
// 字典选项驱动的 Select(消费模式 D):dict 查回来 map 成 SelectItem——
// 消灭各管理页表单里 9 处同构的"硬编码状态选项"样板
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

import { useDict } from '../api/get-dict';

interface DictSelectProps {
  /** 字典类型,如 'sys_normal_disable' */
  dictType: string;
  /** 受控值(字典项的 dictValue) */
  value: string;
  onChange: (value: string) => void;
  /** 透传给 SelectTrigger(FormControl 关联 id / size 等) */
  id?: string;
  disabled?: boolean;
}

/**
 * 字典 Select(受控组件)
 * 后端类比:相当于后端模板的字典下拉组件——选项来自 sys_dict_data 而非硬编码
 *
 * @example
 * <DictSelect dictType="sys_normal_disable" value={field.value} onChange={field.onChange} />
 */
export function DictSelect({
  dictType,
  value,
  onChange,
  id,
  disabled,
}: DictSelectProps) {
  const dict = useDict(dictType);
  // 注:DictOption 契约无 status 字段——停用项过滤由后端 /dict/data/type 接口负责,前端全量渲染
  const options = dict;

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger id={id}>
        <SelectValue placeholder={options.length ? '请选择' : '加载中...'} />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {options.map((d) => (
            <SelectItem key={d.dictValue} value={d.dictValue}>
              {d.dictLabel}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}
