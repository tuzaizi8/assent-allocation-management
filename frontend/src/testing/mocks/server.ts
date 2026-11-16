import { setupServer } from 'msw/node';

// 测试环境注册【完整】handler 集——与 handlers/index.ts 的联调渐进注释解耦:
// 浏览器环境(worker)随后端实现进度注释已上线接口(渐进联调,08 七节规范 3);
// 测试环境始终全量 mock(单元测试不依赖真实后端,08 第二节"测试走另一条路")
import { authHandlers } from './handlers/auth';
import { dictsHandlers } from './handlers/dicts';
import { menusHandlers } from './handlers/menus';

export const server = setupServer(
  ...authHandlers,
  ...menusHandlers,
  ...dictsHandlers,
);
