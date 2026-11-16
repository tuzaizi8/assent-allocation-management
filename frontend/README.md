# Assent Allocation Management Frontend

资产管理与组合分析系统的前端应用。

后端服务见本仓库 [backend/](../backend/)。

## 技术栈

- React 19 + Vite + react-router v7
- TanStack Query v5（服务端状态）
- shadcn/ui v4 + Tailwind CSS v4
- MSW（接口 Mock / E2E Mock Server）
- Recharts（收益曲线 / 热力图 / 直方图等可视化）
- Vitest + Playwright

## 快速开始

```bash
# 需要 Node 20+ 与 pnpm
pnpm install

# 准备环境变量(默认指向本地后端 http://localhost:8000)
cp .env.example .env

# 启动开发服务
pnpm dev
```

默认关闭 MSW 直连真实后端(`VITE_APP_ENABLE_API_MOCKING=false`);需要脱离后端演示时改为 `true`。完整的功能介绍与"启动后第一步"指引见[顶层 README](../README.md)。

## 常用命令

```bash
pnpm lint          # ESLint
pnpm check-types   # TypeScript 类型检查
pnpm test run      # 单元测试(Vitest)
pnpm test:e2e      # E2E 测试(自带 mock server)
pnpm build         # 生产构建
```

## 环境变量说明

| 变量 | 说明 |
|---|---|
| `VITE_APP_API_URL` | 后端 API 地址 |
| `VITE_APP_ENABLE_API_MOCKING` | 是否启用 MSW Mock |
| `VITE_APP_URL` / `VITE_APP_MOCK_API_PORT` | 应用地址 / Mock 服务端口 |
| `VITE_APP_ICP_NO` | 可选。ICP 备案号,部署方自行注入,留空则登录页不显示备案链接 |

## 许可证

[MIT](./LICENSE)
