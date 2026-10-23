PICCOLO_CONF := core.database
export PICCOLO_CONF

# ── Docker ───────────────────────────────────────────────────────────────────

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api

# ── Dev local ─────────────────────────────────────────────────────────────────

install:
	uv sync

dev:
	uv run uvicorn app:app --reload --host 0.0.0.0 --port 8100

worker:
	uv run huey_consumer core.tasks.huey -w 2 -k thread

# ── Migrations ────────────────────────────────────────────────────────────────

# Exemple : make migration app=auth
migration:
	uv run piccolo migrations new $(app) --auto

migrate:
	uv run piccolo migrations forwards all

# ── Qualité ───────────────────────────────────────────────────────────────────

test:
	uv run pytest -v

# PostgreSQL et Redis jetables (compose.test.yml), puis les tests marqués integration
test-integration:
	docker compose -f compose.test.yml up -d --wait
	POSTGRES_HOST=localhost POSTGRES_PORT=5499 POSTGRES_USER=test POSTGRES_PASSWORD=test POSTGRES_DB=test \
	REDIS_URL=redis://localhost:6399/0 ADMIN_EMAIL=admin@genomica-test.org ADMIN_PASSWORD=admin-password-123 \
	uv run pytest -v -m integration

lint:
	uv run ruff check .

# ── Scaffolding ───────────────────────────────────────────────────────────────

# Exemple : make feature name=clients
feature:
	@uv run python scripts/new_feature.py $(name)

.PHONY: up down logs install dev worker migration migrate test test-integration lint feature
