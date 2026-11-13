SHELL := /bin/bash
.DEFAULT_GOAL := help

API_DIR := apps/api
WEB_DIR := apps/web
# .env.local(개인 로컬 설정, gitignore)이 있으면 .env 뒤에 읽어 값을 덮는다.
ENV_FILES := .env $(wildcard .env.local)
COMPOSE := docker compose -f infra/local/docker-compose.yml $(foreach f,$(ENV_FILES),--env-file $(f))
# PROVIDER=fake 처럼 주면 LLM·임베딩 공급자를 이번 실행에만 바꾼다(예: make up PROVIDER=fake)
PROVIDER_ENV := $(if $(PROVIDER),LLM_PROVIDER=$(PROVIDER) EMBEDDING_PROVIDER=$(PROVIDER))
API_EXEC := $(COMPOSE) exec -T $(if $(PROVIDER),-e LLM_PROVIDER=$(PROVIDER) -e EMBEDDING_PROVIDER=$(PROVIDER)) api
PY_DIRS := . ../../jobs ../../ml ../../scripts

# .env(→ .env.local)에서 필요한 값만 읽는다. `-include .env`는 셸 환경변수(LLM_PROVIDER=fake 등)를
# 빈 값으로 덮어쓰기 때문에 쓰지 않는다. ?= 이므로 셸 값이 항상 우선한다. 빈 값은 건너뛴다.
dotenv = $(shell cat $(ENV_FILES) 2>/dev/null | grep -E '^$(1)=.+' | tail -1 | cut -d= -f2-)
POSTGRES_USER ?= $(call dotenv,POSTGRES_USER)
POSTGRES_PASSWORD ?= $(call dotenv,POSTGRES_PASSWORD)
POSTGRES_DB ?= $(call dotenv,POSTGRES_DB)
POSTGRES_PORT ?= $(call dotenv,POSTGRES_PORT)
TEST_DATABASE_URL ?= $(call dotenv,TEST_DATABASE_URL)
EMBEDDING_MODEL ?= $(call dotenv,EMBEDDING_MODEL)
LLM_MODEL ?= $(call dotenv,LLM_MODEL)

# 테스트는 호스트에서 돌기 때문에 compose 내부 호스트명(db) 대신 localhost로 접속한다.
# conftest가 이 URL의 DB 이름 뒤에 _test를 붙인 별도 DB를 만들어 쓴다(개발 DB를 건드리지 않는다).
ifeq ($(strip $(TEST_DATABASE_URL)),)
TEST_DATABASE_URL := postgresql+asyncpg://$(or $(POSTGRES_USER),etf):$(POSTGRES_PASSWORD)@localhost:$(or $(POSTGRES_PORT),5432)/$(or $(POSTGRES_DB),etf_agent)
endif

.PHONY: help
help: ## 사용 가능한 타깃 목록
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: check-env
check-env:
	@test -f .env || { echo ".env가 없습니다. 'cp .env.example .env' 후 값을 채우세요." >&2; exit 1; }

.PHONY: setup
setup: ## 호스트 의존성 설치(uv, npm) — make test/lint용
	cd $(API_DIR) && uv sync --locked
	cd $(WEB_DIR) && npm ci

# ---------- 로컬 스택 ----------
.PHONY: up
up: check-env ## db·api·web 기동(빌드 포함), 헬스체크 통과까지 대기. API 키 없이: make up PROVIDER=fake
	$(PROVIDER_ENV) $(COMPOSE) up -d --build --wait db api web

.PHONY: down
down: check-env ## 모든 컨테이너 중지(볼륨 유지)
	$(COMPOSE) down

.PHONY: restart
restart: check-env ## api 재시작 — seed·ingest·collect 뒤 API의 메모리 캐시를 비운다
	$(COMPOSE) restart api

.PHONY: ps
ps: check-env ## 컨테이너 상태
	$(COMPOSE) ps

.PHONY: logs
logs: check-env ## api 로그 팔로우
	$(COMPOSE) logs -f api

# ---------- 데이터 ----------
.PHONY: migrate
migrate: check-env ## Alembic 마이그레이션 head까지 적용(P1-DA-01)
	$(API_EXEC) alembic upgrade head

.PHONY: seed
seed: check-env ## 샘플 ETF 마스터·시세·공시 적재(P1-DA-02)
	$(API_EXEC) python -m jobs.seed

.PHONY: ingest
ingest: check-env ## 샘플 문서 청킹·임베딩 적재(P1-DA-03). 다른 경로: make ingest ARGS="경로"
	$(API_EXEC) python -m jobs.ingest $(or $(ARGS),/workspace/data/samples/docs)

.PHONY: collect
collect: check-env ## 공공데이터포털·DART 수집(키가 없으면 안내만 출력)
	$(API_EXEC) python -m jobs.collector $(ARGS)

# ---------- 품질 ----------
.PHONY: test
test: ## API 테스트(LLM_PROVIDER=fake, db 컨테이너 필요: make up)
	cd $(API_DIR) && TEST_DATABASE_URL='$(TEST_DATABASE_URL)' LLM_PROVIDER=fake EMBEDDING_PROVIDER=fake uv run pytest

.PHONY: lint
lint: ## ruff(api·jobs·ml·scripts) + eslint + prettier + tsc
	cd $(API_DIR) && uv run ruff check $(PY_DIRS) && uv run ruff format --check $(PY_DIRS)
	cd $(WEB_DIR) && npm run lint && npm run format:check && npm run typecheck

.PHONY: fmt
fmt: ## 자동 포맷(ruff, prettier)
	cd $(API_DIR) && uv run ruff check --fix $(PY_DIRS) && uv run ruff format $(PY_DIRS)
	cd $(WEB_DIR) && npm run format

.PHONY: eval
eval: check-env ## 평가 리포트(JSON + 표). 예: make eval PROVIDER=fake
	$(API_EXEC) python -m ml.eval $(ARGS)

.PHONY: demo
demo: check-env ## 대표 질문 6개 실행(LLM_API_KEY 필요). 예: make demo PROVIDER=fake
	$(API_EXEC) python /workspace/scripts/demo.py $(ARGS)

# ---------- 웹 ----------
.PHONY: web-build
web-build: ## 웹 정적 빌드(apps/web/dist)
	cd $(WEB_DIR) && npm run build
