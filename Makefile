SHELL := /bin/bash
.DEFAULT_GOAL := help

API_DIR := apps/api
WEB_DIR := apps/web
COMPOSE := docker compose -f infra/mvp/docker-compose.yml --env-file .env

# .env 값을 make 변수로 읽는다(값에 `$`, `#`는 쓰지 않는다).
-include .env

# 테스트는 호스트에서 돌기 때문에 compose 내부 호스트명(postgres) 대신 localhost로 접속한다.
ifeq ($(strip $(TEST_DATABASE_URL)),)
TEST_DATABASE_URL := postgresql+asyncpg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(or $(POSTGRES_PORT),5432)/$(POSTGRES_DB)
endif

.PHONY: help
help: ## 사용 가능한 타깃 목록
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: check-env
check-env:
	@test -f .env || { echo ".env가 없습니다. 'cp .env.example .env' 후 값을 채우세요." >&2; exit 1; }

.PHONY: setup
setup: ## 로컬 의존성 설치(uv, npm)와 pre-commit 훅 등록
	cd $(API_DIR) && uv sync --locked
	cd $(WEB_DIR) && npm ci
	uvx pre-commit install

.PHONY: dev
dev: check-env ## dev 프로필 기동(api + postgres), 헬스체크 통과까지 대기
	$(COMPOSE) --profile dev up -d --build --wait api postgres

.PHONY: dev-llm
dev-llm: check-env ## dev + 컨테이너 Ollama까지 기동(GPU 없는 맥에서는 네이티브 Ollama 권장)
	$(COMPOSE) --profile dev --profile ollama up -d --build --wait api postgres ollama

.PHONY: down
down: check-env ## 모든 컨테이너 중지(볼륨 유지)
	$(COMPOSE) --profile dev --profile ollama down

.PHONY: logs
logs: check-env ## api 로그 팔로우
	$(COMPOSE) logs -f api

.PHONY: migrate
migrate: check-env ## Alembic 마이그레이션을 api 컨테이너에서 head까지 적용
	$(COMPOSE) run --rm --no-deps api alembic upgrade head

.PHONY: test
test: ## API 테스트(로컬 postgres 필요: make dev)
	cd $(API_DIR) && DATABASE_URL='$(TEST_DATABASE_URL)' uv run pytest

.PHONY: lint
lint: ## ruff + eslint + prettier 검사
	cd $(API_DIR) && uv run ruff check . && uv run ruff format --check .
	cd $(WEB_DIR) && npm run lint && npm run format:check

.PHONY: fmt
fmt: ## 자동 포맷(ruff, prettier)
	cd $(API_DIR) && uv run ruff check --fix . && uv run ruff format .
	cd $(WEB_DIR) && npm run format

.PHONY: web-dev
web-dev: ## Vite 개발 서버
	cd $(WEB_DIR) && npm run dev

.PHONY: web-build
web-build: ## 웹 정적 빌드(apps/web/dist)
	cd $(WEB_DIR) && npm run build
