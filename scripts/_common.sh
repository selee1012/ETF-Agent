# run-*.sh 공용 함수. 직접 실행하지 않고 source 한다.
# shellcheck shell=bash

info() { printf '\033[36m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
fail() {
  printf '\033[31m✖ %s\033[0m\n' "$*" >&2
  exit 1
}

rand_hex() { LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c "$1"; }

# .env에서 KEY의 값이 비어 있거나 KEY가 없을 때만 VALUE로 채운다.
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

# .env → .env.local 순으로 읽어 마지막으로 정의된 비어 있지 않은 값(앱·compose와 같은 우선순위).
env_get() {
  cat .env .env.local 2>/dev/null | grep -E "^$1=.+" | tail -1 | cut -d= -f2- |
    sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/' || true
}

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

# .env가 없으면 .env.example로 만들고 DB 비밀번호·JWT 키를 무작위로 채운다(기존 값은 유지).
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
  user="$(grep -E '^POSTGRES_USER=' .env | tail -1 | cut -d= -f2-)"
  pw="$(grep -E '^POSTGRES_PASSWORD=' .env | tail -1 | cut -d= -f2-)"
  db="$(grep -E '^POSTGRES_DB=' .env | tail -1 | cut -d= -f2-)"
  set_env_if_empty DATABASE_URL "postgresql+asyncpg://${user}:${pw}@db:5432/${db}"
}

# make up 이후: 마이그레이션 → 샘플 시드 → 문서 ingest(임베딩 모델이 바뀌었으면 자동 재임베딩)
prepare_data() {
  info "마이그레이션"
  make migrate "$@"
  info "샘플 ETF·시세·공시 적재"
  make seed "$@"
  info "샘플 문서 ingest"
  make ingest "$@"
}
