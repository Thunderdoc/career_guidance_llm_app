.PHONY: install dev api web test lint eval build catalog docker

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

lint:
	ruff check . && ruff format --check . && cd frontend && npx eslint . && npx tsc --noEmit

eval:
	python -m eval.run

catalog:
	python scripts/build_catalog.py --source $(ONET_DIR) --out data/catalog/occupations.json

build:
	cd frontend && NEXT_EXPORT=1 npm run build

docker:
	docker compose up --build
