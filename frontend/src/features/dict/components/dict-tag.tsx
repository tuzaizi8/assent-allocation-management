// src/features/dict/components/dict-tag.tsx
import { useDict } from '../api/get-dict';

interface DictTagProps {
  dictType: string; // 字典类型，如 'sys_user_sex'
  value: string; // 字典值，如 '0'
  fallback?: string; // 字典里找不到时的兜底文本（默认用 value）
}

/**
 * 字典标签组件：根据 dictType + value 渲染带样式的标签
 * 有对应字典项时渲染带 cssClass 的标签，找不到时渲染兜底文本
 *
 * 后端类比：相当于后端模板引擎的 {{ dict_tag('sys_user_sex', user.sex) }}
 *
 * @example
 * <DictTag dictType="sys_user_sex" value="0" />
 * // → <span class="tag-primary">男</span>
 */
export function DictTag({ dictType, value, fallback }: DictTagProps) {
  const dict = useDict(dictType);
  const option = dict.find((d) => d.dictValue === value);

  // 找不到对应字典项：渲染兜底文本（默认用 value）
  if (!option) {
    return <span>{fallback ?? value}</span>;
  }

  // 找到：渲染带 cssClass 样式的标签
  return <span className={option.cssClass}>{option.dictLabel}</span>;
}
