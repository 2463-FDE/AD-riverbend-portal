.PHONY: up down logs build seed psql frontend-dev fmt

up:            ## start the whole stack
	docker compose up -d

down:          ## stop the stack
	docker compose down

build:         ## build all images
	docker compose build

logs:          ## tail logs
	docker compose logs -f

seed:          ## load schema + demo data (re-runs against a running db)
	docker compose exec -T postgres psql -U $${DB_USER:-riverbend_app} -d $${DB_NAME:-riverbend} < db/schema.sql
	docker compose exec -T postgres psql -U $${DB_USER:-riverbend_app} -d $${DB_NAME:-riverbend} < db/seed/seed.sql

psql:          ## open a psql shell
	docker compose exec postgres psql -U $${DB_USER:-riverbend_app} -d $${DB_NAME:-riverbend}

frontend-dev:  ## run the Next.js dev server
	cd frontend && npm install && npm run dev

config:        ## validate the compose file
	docker compose config -q && echo "compose OK"
