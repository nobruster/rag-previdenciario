.PHONY: up down logs ps test lint fmt api install

install:
	pip install -e ".[dev]"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

test:
	pytest -v

lint:
	ruff check src tests

fmt:
	ruff check --fix src tests

api:
	uvicorn isp_rag.api.main:app --reload --port $${API_PORT:-8000}
