// src/components/shared/dict-filter-tabs.tsx —— 字典驱动的多态状态过滤 Tabs
// 与 status-filter-tabs.tsx(两态硬编码,users/roles/dicts 三页在用)的差异:
// 状态值集合由字典动态决定(如持仓状态三态),硬编码两态件无法表达,故另立本件而非
// 给旧件长业务分支——两件并存是刻意的,等两态页也字典化后再收敛
// 字典数据由页面传入而非本件内调 useDict:useDict 位于 features/dict,
// 共享层引入它会形成 shared → features 的反向依赖(status-filter-tabs 同款约束)
import * as React from 'react';

import {
  Tabs,
  TabsList,
  TabsTrigger,
} from '@/components/animate-ui/components/radix/tabs';
import { Badge } from '@/components/ui/badge';

/** 字典选项的结构化形态(避免共享层依赖 features/dict 的 DictOption 类型) */
type DictLikeOption = { dictValue: string; dictLabel: string };

export type DictFilterTabsProps = {
  value: string;
  onValueChange: (value: string) => void;
  /**
   * 参与计数的数据行(items 派生是「当前页」口径,仅兜底;
   * 服务端分页+筛选的页面必须改传 counts,否则切档后其它档计数会塌成 0)
   */
  items?: readonly { status?: string | null }[];
  /** 字典选项:档位与文案的来源,缺失时本件渲染纯「全部」档 */
  dict?: readonly DictLikeOption[];
  /** 各档位计数(服务端全量口径,优先于 items 派生;key 为 dictValue) */
  counts?: Record<string, number>;
  allLabel?: string;
};

// 稳定空数组兜底(dict 未传时引用不变,避免 useMemo 依赖每次 render 重建)
const EMPTY_DICT: DictLikeOption[] = [];

export function DictFilterTabs({
  value,
  onValueChange,
  items,
  dict,
  counts,
  allLabel = '全部',
}: DictFilterTabsProps) {
  const options = dict ?? EMPTY_DICT;

  // 计数双源:服务端全量 counts 优先;items 派生是「当前页」口径,仅作无 counts 时的兜底
  const countMap = React.useMemo(() => {
    if (counts) {
      return new Map(Object.entries(counts));
    }
    const map = new Map<string, number>();
    for (const option of options) {
      let count = 0;
      for (const item of items ?? []) {
        if (item.status != null && String(item.status) === option.dictValue) {
          count += 1;
        }
      }
      map.set(option.dictValue, count);
    }
    return map;
  }, [counts, items, options]);

  return (
    <Tabs value={value} onValueChange={onValueChange}>
      <TabsList>
        <TabsTrigger value="all">{allLabel}</TabsTrigger>
        {options.map((option) => (
          <TabsTrigger key={option.dictValue} value={option.dictValue}>
            {option.dictLabel}{' '}
            <Badge variant="secondary">
              {countMap.get(option.dictValue) ?? 0}
            </Badge>
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
