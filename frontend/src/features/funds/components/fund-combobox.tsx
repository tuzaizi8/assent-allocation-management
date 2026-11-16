// 基金候选选择器(fund 域组件):建仓/买入与「添加基金净值」两处共用同一套选中语义。
// 搜索复用净值页的 useFundCandidates(内置 300ms 防抖 + 30s 缓存);shouldFilter=false 是刻意的:
// 过滤在后端做(fund 表两万多行,前端过滤候选集没有意义)。
// 选中反馈落在输入框本身——用基金名称占用输入框,而不是在输入框下方另起一行小字回报选了谁。
import { Loader2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { useFundCandidates } from '@/features/funds/api/get-fund-navs';
import type { Fund } from '@/features/funds/api/get-funds';
import { cn } from '@/utils/cn';

const EMPTY_CANDIDATES: Fund[] = [];

type FundComboboxProps = {
  /** 选中变化(取消选中传 null):调用方据此写表单 / 启停提交按钮 */
  onChange: (fund: Fund | null) => void;
  /** 候选请求开关:常驻挂载的弹窗传 open,收起时零请求 */
  active?: boolean;
  placeholder?: string;
  className?: string;
  /** 候选列表高度类(持仓弹窗窄用 max-h-40,净值弹窗用 max-h-64) */
  listClassName?: string;
};

export function FundCombobox({
  onChange,
  active = true,
  placeholder = '输入基金代码或名称搜索',
  className,
  listClassName = 'max-h-64',
}: FundComboboxProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  // 输入框内容:未选中时是搜索词,选中后是基金名称(选中反馈就落在输入框本身)
  const [keyword, setKeyword] = useState('');
  const [selected, setSelected] = useState<Fund | null>(null);
  // 候选列表只在展开时渲染:选中即收起,聚焦/输入即重新展开
  const [expanded, setExpanded] = useState(true);
  // 候选走公共端点(仅登录,无 fund:fund:list 要求):选基金是建仓的核心路径,
  // 不该被「基金管理」菜单权限卡住——详见 features/funds/api/get-funds 的 getFundCandidates
  const { data, isFetching } = useFundCandidates(keyword, active);
  const items = data?.data ?? EMPTY_CANDIDATES;

  // 常驻挂载的弹窗(净值页)靠 active 开合:重新打开即清掉上次的关键词与选中,
  // 否则输入框会带着上次的基金名称、而选中态已归零,看着像"选好了"却提交不了
  useEffect(() => {
    if (!active) return;
    setKeyword('');
    setSelected(null);
    setExpanded(true);
  }, [active]);

  const handleInputChange = (value: string) => {
    // 输入即视为重新搜索,必须取消上次选中:否则提交按钮仍指向旧基金,
    // 用户看着新列表却提交了上一只(实测反馈过的坑)
    setSelected(null);
    onChange(null);
    setKeyword(value);
    setExpanded(true);
  };

  const handleSelect = (fund: Fund) => {
    setSelected(fund);
    setKeyword(fund.name);
    setExpanded(false);
    onChange(fund);
    // 主动失焦:此刻输入框是"展示位"而不是编辑位。留着焦点的话,光标停在名称末尾,
    // 下一次输入会追加成「华夏大盘精选混合000011」这种搜不出东西的关键词;
    // 失焦后用户再点一下输入框才会聚焦→全选,一敲键盘整串替换
    inputRef.current?.blur();
  };

  return (
    <Command shouldFilter={false} className={className}>
      <CommandInput
        ref={inputRef}
        value={keyword}
        onValueChange={handleInputChange}
        placeholder={placeholder}
        onFocus={(event) => {
          setExpanded(true);
          event.currentTarget.select();
        }}
      />
      {expanded && (
        <CommandList className={listClassName}>
          {isFetching ? (
            <div className="text-muted-foreground flex items-center justify-center gap-2 py-6 text-sm">
              <Loader2 className="size-4 animate-spin" />
              搜索中…
            </div>
          ) : (
            <>
              <CommandEmpty>
                {keyword.trim() ? '未找到匹配的基金' : '输入基金代码或名称搜索'}
              </CommandEmpty>
              <CommandGroup>
                {items.map((fund) => (
                  <CommandItem
                    key={fund.fundId}
                    value={fund.code}
                    onSelect={() => handleSelect(fund)}
                    className={cn(
                      selected?.fundId === fund.fundId &&
                        'bg-accent text-accent-foreground',
                    )}
                  >
                    <span className="font-mono text-xs">{fund.code}</span>
                    <span className="flex-1 truncate">{fund.name}</span>
                    {fund.fundType && (
                      <span className="text-muted-foreground text-xs">
                        {fund.fundType}
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          )}
        </CommandList>
      )}
    </Command>
  );
}
