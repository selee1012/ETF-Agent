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
# 이미 값이 있는 항목은 건드리지 않는다. 실제 모델로 쓰려면 ./scripts/run-local.sh
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/_common.sh
source scripts/_common.sh
CMD="${1:-up}"

start_stack() {
  info "db·api·web 기동 (PROVIDER=fake)"
  make up PROVIDER=fake
  prepare_data PROVIDER=fake
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
