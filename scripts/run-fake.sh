#!/usr/bin/env bash
# Ollama 없이 로컬 스택 실행(LLM·임베딩 모두 fake).
#
#   ./scripts/run-fake.sh          # .env 준비 → db·api·web 기동 → migrate → seed → ingest
#   ./scripts/run-fake.sh demo     # 위 + 대표 질문 6개 실행
#   ./scripts/run-fake.sh eval     # 위 + 평가 리포트
#   ./scripts/run-fake.sh test     # 호스트에서 make test (uv 필요, db 컨테이너 사용)
#   ./scripts/run-fake.sh down     # 컨테이너 중지(볼륨 유지)
#
# .env가 없으면 .env.example을 복사하고 DB 비밀번호·JWT 키를 무작위로 채운다.
# 이미 값이 있는 항목은 건드리지 않는다.
set -euo pipefail

cd "$(dirname "$0")/.."
CMD="${1:-up}"

info() { printf '\033[36m▶ %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

rand_hex() { LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c "$1"; }

# KEY의 값이 비어 있거나 KEY가 없을 때만 VALUE로 채운다.
set_env_if_empty() {
  local key="$1" value="$2" tmp
  if grep -qE "^${key}=" .env; then
    tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" '
      index($0, k "=") == 1 && length($0) == length(k) + 1 { print k "=" v; next }
      { print }
    ' .env >"$tmp" && mv "$tmp" .env
  else
    printf '%s=%s\n' "$key" "$value" >>.env
  fi
}

env_get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

ensure_docker() {
  command -v docker >/dev/null || fail "docker가 없습니다. Docker Desktop 또는 colima를 설치하세요."
  if ! docker info >/dev/null 2>&1; then
    if command -v colima >/dev/null; then
      info "Docker 데몬이 꺼져 있어 colima를 시작합니다"
      colima start
    else
      fail "Docker 데몬이 실행 중이 아닙니다. Docker Desktop을 켜 주세요."
    fi
  fi
}

ensure_env() {
  if [[ ! -f .env ]]; then
    info ".env가 없어 .env.example로 만듭니다"
    cp .env.example .env
  fi
  set_env_if_empty APP_ENV local
  set_env_if_empty POSTGRES_USER etf
  set_env_if_empty POSTGRES_DB etf_agent
  set_env_if_empty POSTGRES_PORT 5432
  set_env_if_empty POSTGRES_PASSWORD "$(rand_hex 32)"
  set_env_if_empty LOCAL_JWT_SECRET "$(rand_hex 64)"
  local user pw db
  user="$(env_get POSTGRES_USER)"
  pw="$(env_get POSTGRES_PASSWORD)"
  db="$(env_get POSTGRES_DB)"
  set_env_if_empty DATABASE_URL "postgresql+asyncpg://${user}:${pw}@db:5432/${db}"
}

start_stack() {
  info "db·api·web 기동 (PROVIDER=fake)"
  make up PROVIDER=fake
  info "마이그레이션"
  make migrate
  info "샘플 ETF·시세·공시 적재"
  make seed
  info "샘플 문서 ingest (fake 임베딩)"
  make ingest PROVIDER=fake
  cat <<'EOF'

✅ 준비 완료 (LLM_PROVIDER=fake — 답변은 근거 문서 발췌 수준입니다)
  웹:       http://localhost:5173   (아무 이메일로 로그인, 운영 화면은 admin@local.test)
  API:      http://localhost:8000/docs
  메트릭:   http://localhost:8000/metrics
  중지:     ./scripts/run-fake.sh down
EOF
}

case "$CMD" in
  up)
    ensure_docker
    ensure_env
    start_stack
    ;;
  demo | eval)
    ensure_docker
    ensure_env
    start_stack
    info "make $CMD (fake)"
    make "$CMD" PROVIDER=fake
    ;;
  test)
    ensure_docker
    ensure_env
    command -v uv >/dev/null || fail "make test에는 uv가 필요합니다: https://docs.astral.sh/uv/"
    make up PROVIDER=fake
    (cd apps/api && uv sync --locked >/dev/null)
    make test
    ;;
  down)
    make down
    ;;
  *)
    fail "알 수 없는 명령: $CMD (up | demo | eval | test | down)"
    ;;
esac
