#!/usr/bin/env bash
# 개인용 로컬 실행: .env.local(gitignore)의 모델 설정(기본 OpenAI API)으로 스택을 올린다.
#
#   ./scripts/run-local.sh         # .env·.env.local 준비 → 키 확인 → 기동 → migrate·seed·ingest
#   ./scripts/run-local.sh down    # 컨테이너 중지(볼륨 유지)
#   ./scripts/run-local.sh logs    # api 로그
#
# .env.local이 없으면 .env.local.example(기본: gpt-5.4-nano + text-embedding-3-small)로 만든다.
# OpenAI 키는 .env 또는 .env.local의 LLM_API_KEY에 넣는다.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/_common.sh
source scripts/_common.sh
CMD="${1:-up}"

check_models() {
  local provider llm_url llm_model emb_provider emb_url emb_model
  provider="$(env_get LLM_PROVIDER)"
  provider="${provider:-openai_compat}"
  [[ "$provider" == "fake" ]] && warn "LLM_PROVIDER=fake 입니다. 실제 모델은 .env.local에서 설정하세요."
  llm_url="$(env_get LLM_BASE_URL)"
  llm_url="${llm_url:-https://api.openai.com/v1}"
  llm_model="$(env_get LLM_MODEL)"
  llm_model="${llm_model:-gpt-5.4-nano}"
  emb_provider="$(env_get EMBEDDING_PROVIDER)"
  emb_provider="${emb_provider:-$provider}"
  emb_url="$(env_get EMBEDDING_BASE_URL)"
  emb_url="${emb_url:-$llm_url}"
  emb_model="$(env_get EMBEDDING_MODEL)"
  emb_model="${emb_model:-text-embedding-3-small}"

  if [[ ("$provider" == "openai_compat" && "$llm_url" == *"api.openai.com"*) ||
    ("$emb_provider" == "openai_compat" && "$emb_url" == *"api.openai.com"*) ]]; then
    [[ -n "$(env_get LLM_API_KEY)" ]] ||
      fail "OpenAI API 키가 없습니다. .env 또는 .env.local에 LLM_API_KEY=… 를 넣으세요"
    warn "OpenAI API 사용: 질문과 검색된 문서 일부가 OpenAI로 전송됩니다"
  fi
  info "생성: $provider / $llm_model  ·  임베딩: $emb_provider / $emb_model"
}

case "$CMD" in
  up)
    ensure_docker
    ensure_env
    if [[ ! -f .env.local ]]; then
      info ".env.local이 없어 .env.local.example로 만듭니다(gitignore 대상)"
      cp .env.local.example .env.local
    fi
    check_models
    info "db·api·web 기동"
    make up
    prepare_data
    cat <<'MSG'

✅ 준비 완료 (.env.local 설정 사용)
  웹:       http://localhost:5173   (아무 이메일로 로그인, 운영 화면은 admin@local.test)
  API:      http://localhost:8000/docs
  로그:     ./scripts/run-local.sh logs
  중지:     ./scripts/run-local.sh down
  설정 변경: .env.local 수정 후 ./scripts/run-local.sh 다시 실행
MSG
    ;;
  down)
    make down
    ;;
  logs)
    make logs
    ;;
  *)
    fail "알 수 없는 명령: $CMD (up | down | logs)"
    ;;
esac
