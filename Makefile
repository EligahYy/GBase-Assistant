.PHONY: dev-backend dev-frontend install test lint migrate

# ── 开发 ─────────────────────────────────────────────────────────────────────────
dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

# ── 安装依赖 ──────────────────────────────────────────────────────────────────────
install:
	cd backend && uv sync
	cd frontend && npm install

# ── 测试 ─────────────────────────────────────────────────────────────────────────
test:
	cd backend && uv run pytest -v

# ── 代码检查 ──────────────────────────────────────────────────────────────────────
lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint

# ── 数据库 ────────────────────────────────────────────────────────────────────────
migrate:
	cd backend && uv run alembic upgrade head

migration:
	cd backend && uv run alembic revision --autogenerate -m "$(msg)"
