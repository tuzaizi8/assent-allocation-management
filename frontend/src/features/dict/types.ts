// src/features/dict/types.ts

// 后端 /dict/data/type/:dictType 返回的字典选项类型（对应若依 sys_dict_data 表）
export interface DictOption {
  dictLabel: string; // 显示文本，如 '男'
  dictValue: string; // 实际值，如 '0'
  dictType: string; // 字典类型，如 'sys_user_sex'
  cssClass?: string; // 样式类（表格标签着色用），如 'tag-success'
}
