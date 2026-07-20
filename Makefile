.PHONY: up down logs ps build seed seed-gen psql test frontend-dev config

# Scoped gateway->ai-assistant secret file. Compose refuses to parse when a
# listed env_file is missing, so every compose target depends on this. The
# template ships the secret EMPTY on purpose: AI calls fail closed (503) until
# a real value is generated (see .env.ai-proxy.example).
.env.ai-proxy:
	cp .env.ai-proxy.example .env.ai-proxy

up: .env.ai-proxy   ## start the whole stack
	docker compose up -d

down: .env.ai-proxy ## stop the stack
	docker compose down

logs: .env.ai-proxy ## tail logs
	docker compose logs -f

ps: .env.ai-proxy   ## service status
	docker compose ps

build: .env.ai-proxy ## build all images
	docker compose build

seed: .env.ai-proxy ## load schema + demo data (re-runs against a running db)
	docker compose exec -T postgres psql -U $${DB_USER:-riverbend_app} -d $${DB_NAME:-riverbend} < db/schema.sql
	docker compose exec -T postgres psql -U $${DB_USER:-riverbend_app} -d $${DB_NAME:-riverbend} < db/seed/seed.sql

seed-gen:      ## regenerate db/seed/seed.sql from the generator (deterministic)
	python3 db/seed/generate_seed.py > db/seed/seed.sql

psql: .env.ai-proxy ## open a psql shell
	docker compose exec postgres psql -U $${DB_USER:-riverbend_app} -d $${DB_NAME:-riverbend}

test:          ## run unit tests (no infra needed)
	pip install -r requirements-dev.txt >/dev/null
	pytest -m "not integration" -q

frontend-dev:  ## run the Next.js dev server
	cd frontend && npm install && npm run dev

config: .env.ai-proxy ## validate the compose file
	docker compose config -q && echo "compose OK"
