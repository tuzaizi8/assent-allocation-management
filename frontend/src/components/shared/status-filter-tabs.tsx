// src/components/shared/status-filter-tabs.tsx —— 状态过滤 Tabs(全部 / 正常 / 停用 + Badge 计数)
// users/roles/dicts 三页逐字重复的 Tabs 统一收口;视觉与交互结果与页内实现一致
// 计数由本件内部从 items 派生:三页原本的派生表达式完全一致
// (rows.filter(r => r.status === '0'/'1').length),抽进来后页面可少两行
// 字典数据由页面传入而非本件内调 useDict:useDict 位于 features/dict,
// 共享层引入它会形成 shared → features 的反向依赖(现有 shared 全部只依赖 components/ui),
// 故这里按结构化类型接收字典选项,沿用 data-table-shell 的 duck typing 先例
import * as React from 'react';

import {
  Tabs,
  TabsList,
  TabsTrigger,
} from '@/components/animate-ui/components/radix/tabs';
import { Badge } from '@/components/ui/badge';

/** 字典选项的结构化形态(避免共享层依赖 features/dict 的 DictOption 类型) */
type DictLikeOption = { dictValue: string; dictLabel: string };

export type StatusFilterTabsProps = {
  value: string;
  onValueChange: (value: string) => void;
  /**
   * 参与计数的数据行(传当前页 rows 即可,与页面原本的派生口径一致)
   * status 允许 null:后端 sys_user / sys_dict_type 的 status 均为 string | null
   */
  items: readonly { status?: string | null }[];
  /** 字典选项(页面用 useDict('sys_normal_disable') 取到后传入) */
  dict?: readonly DictLikeOption[];
  allLabel?: string;
  /** 字典缺失时的回退标签 */
  normalLabel?: string;
  disabledLabel?: string;
};

const NORMAL_VALUE = '0';
const DISABLED_VALUE = '1';

export function StatusFilterTabs({
  value,
  onValueChange,
  items,
  dict,
  allLabel = '全部',
  normalLabel = '正常',
  disabledLabel = '停用',
}: StatusFilterTabsProps) {
  // 一次 O(n) 遍历算两个计数;n 为当前页行数,用 useMemo 避免无关重渲染重复计算
  const { normalCount, disabledCount } = React.useMemo(() => {
    let normal = 0;
    let disabled = 0;
    for (const item of items) {
      if (item.status === NORMAL_VALUE) normal += 1;
      else if (item.status === DISABLED_VALUE) disabled += 1;
    }
    return { normalCount: normal, disabledCount: disabled };
  }, [items]);

  const labelOf = (dictValue: string, fallback: string) =>
    dict?.find((d) => d.dictValue === dictValue)?.dictLabel ?? fallback;

  return (
    <Tabs value={value} onValueChange={onValueChange}>
      <TabsList>
        <TabsTrigger value="all">{allLabel}</TabsTrigger>
        <TabsTrigger value={NORMAL_VALUE}>
          {labelOf(NORMAL_VALUE, normalLabel)}{' '}
          <Badge variant="secondary">{normalCount}</Badge>
        </TabsTrigger>
        <TabsTrigger value={DISABLED_VALUE}>
          {labelOf(DISABLED_VALUE, disabledLabel)}{' '}
          <Badge variant="secondary">{disabledCount}</Badge>
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );
}
