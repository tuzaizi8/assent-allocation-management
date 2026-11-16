# Assent Allocation Management

资产管理与组合分析系统(全栈 Monorepo)。

```
├── frontend/   # React 19 + Vite + TanStack Query + shadcn/ui + Tailwind v4 + MSW
├── backend/    # FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL + Redis + AkShare
└── .github/    # Monorepo CI(前后端门禁按路径触发)
```

## 快速开始

### 后端(需要 Python 3.12+ 与运行中的 PostgreSQL / Redis)

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env.dev        # 按需修改 DB_PASSWORD / JWT_SECRET_KEY
uvicorn main:app --reload       # http://localhost:8000/api/docs
```

首次启动自动建表并创建联调管理员 `admin@assent.local / password123`,仅限本地联调,真实环境部署后必须立即修改。

### 前端(需要 Node 20+ 与 pnpm)

```bash
cd frontend
pnpm install
cp .env.example .env            # 默认指向 http://localhost:8000
pnpm dev                        # http://localhost:3000
```

默认开启 MSW Mock(`VITE_APP_ENABLE_API_MOCKING=true`),可脱离后端独立跑通全部页面;对接真实后端时置为 `false`。

## 环境变量

各子目录的 `.env.example` 含全部变量与注释,复制为 `.env`(前端)/`.env.dev`(后端)后按需修改,均不会提交。

## CI

`.github/workflows/ci.yml` 按路径触发:改动 `frontend/**` 跑前端 lint/类型/测试,改动 `backend/**` 跑 ruff/pytest。

## 许可证

[MIT](./LICENSE)
