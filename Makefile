.PHONY: install dev up down logs migrate migration lint test worker demo benchmark

install:
	pip install -e ".[dev]"

dev:
	uvicorn llmops_gateway.main:app --reload --host 0.0.0.0 --port 8000

worker:
	arq llmops_gateway.workers.worker_app.WorkerSettings

up:
	docker compose up -d postgres redis qdrant otel-collector prometheus grafana gateway worker

up-infra:
	docker compose up -d postgres redis qdrant otel-collector prometheus grafana

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	alembic upgrade head

migration:
	alembic revision --autogenerate -m "$(m)"

lint:
	ruff check src tests
	mypy src

test:
	pytest

demo:
	bash scripts/demo.sh

benchmark:
	python scripts/benchmark_gateway.py --requests 20
