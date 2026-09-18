.PHONY: install dev api web test cov lint eval build catalog docker ci blackbox blackbox-prod smoke-local

install:
	pip install -r requirements-dev.txt && cd frontend && npm ci

api:
	uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

web:
	cd frontend && npm run dev

dev:
	@echo "Run 'make api' and 'make web' in two terminals; open http://localhost:3000"

test:
	pytest -q -p no:warnings

cov:
	pytest -q -p no:warnings --cov=career_guidance --cov=backend --cov-report=term-missing --cov-fail-under=85

lint:
	ruff check . && ruff format --check . && cd frontend && npx eslint . && npx tsc --noEmit

eval:
	python -m eval.run --min-hit 0.75

# Black-box round: speaks HTTP only, so it also runs against production.
#   make blackbox                        (local uvicorn on :8000)
#   make blackbox-prod                   (Render + Vercel URLs from docs/DEPLOY.md)
#   make blackbox API=https://…          (any other deployment)
API ?= http://127.0.0.1:8000
PROD_API ?= https://career-guidance-llm-app.onrender.com
PROD_WEB ?= https://career-guidance-web-sigma.vercel.app

blackbox:
	python scripts/smoke_api.py --base $(API)

blackbox-prod:
	python scripts/smoke_api.py --base $(PROD_API)
	python scripts/smoke_api.py --base $(PROD_WEB)

catalog:
	python scripts/build_catalog.py --source $(ONET_DIR) --out data/catalog/occupations.json

build:
	cd frontend && NEXT_EXPORT=1 npm run build

docker:
	docker compose up --build

ci: lint test cov eval

# Same as `ci` plus the black-box round; expects the API to be running.
smoke-local:
	python scripts/smoke_api.py --base http://127.0.0.1:8000
