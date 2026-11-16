# Assent Allocation Management Backend

资产管理与组合分析系统的后端服务,基于 FastAPI。

前端应用见本仓库 [frontend/](../frontend/)。

## 技术栈

- Python 3.12 + FastAPI + uvicorn
- SQLAlchemy 2.0 (async) + PostgreSQL
- Redis (会话与缓存)
- AkShare (基金/指数行情数据源)
- ruff + pytest

## 快速开始

```bash
# 需要 Python 3.12 与运行中的 PostgreSQL / Redis
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# 准备环境变量,按需修改 DB_PASSWORD / JWT_SECRET_KEY 等
cp .env.example .env.dev
```

`JWT_SECRET_KEY` 生成方式:

```bash
openssl rand -base64 32
```

## 启动

```bash
# 开发模式
uvicorn main:app --reload

# 生产模式
uvicorn main:app --workers 4
```

首次启动会自动建表并执行种子初始化,创建联调管理员:

```
账号: admin@assent.local
密码: password123
```

> 仅限本地联调,任何真实环境部署后必须立即修改账号与密码。

启动后访问 `http://localhost:8000/api/docs` 查看接口文档(路径前缀默认 `/api`,由 `APP_ROOT_PATH` 控制)。

## 常用命令

```bash
ruff check .     # Lint
pytest -q        # 测试
```

## 许可证

[MIT](./LICENSE)
