// src/lib/download.ts —— 浏览器落盘工具
// 下载必须由前端发起 a[download]:接口要带鉴权头,不能直接用 <a href> 指向后端地址
/** 把二进制响应存成文件:临时 objectURL + a[download],用完立刻 revoke 释放内存 */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
