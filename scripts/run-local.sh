#!/usr/bin/env bash
# 개인용 로컬 실행: .env.local(gitignore)의 모델 설정으로 스택을 올린다.
#
#   ./scripts/run-local.sh         # .env·.env.local 준비 → (Ollama면) 모델 받기 → 기동 → migrate·seed·ingest
#   ./scripts/run-local.sh down    # 컨테이너 중지(볼륨 유지)
#   ./scripts/run-local.sh logs    # api 로그
#
# .env.local이 없으면 .env.local.example(기본: Ollama gemma3:12b + snowflake-arctic-embed2)로 만든다.
# OpenAI API를 쓰려면 .env.local의 '방식 2' 주석을 풀고 LLM_API_KEY를 넣는다.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/_common.sh
source scripts/_common.sh
CMD="${1:-up}"

OLLAMA_HOST_URL="http://localhost:11434"

is_ollama_url() { [[ "$1" == *":11434"* ]]; }

ensure_ollama() {
  command -v ollama >/dev/null || fail "ollama가 없습니다: brew install ollama && brew services start ollama"
  if ! curl -fsS --max-time 3 "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1; then
    if command -v brew >/dev/null; then
      info "Ollama 서버를 시작합니다(brew services)"
      brew services start ollama >/dev/null
    else
      fail "Ollama 서버가 꺼져 있습니다. 'ollama serve'를 실행하세요."
    fi
    for _ in $(seq 1 20); do
      curl -fsS --max-time 2 "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1 && return 0
      sleep 1
    done
    fail "Ollama 서버가 응답하지 않습니다($OLLAMA_HOST_URL)"
  fi
}

ensure_ollama_model() {
  local m="$1"
  [[ -n "$m" ]] || return 0
  if ollama show "$m" >/dev/null 2>&1; then
    info "Ollama 모델 확인: $m"
  else
    info "Ollama 모델 받는 중: $m (처음 한 번만, 크기에 따라 수 분)"
    ollama pull "$m"
  fi
}

check_models() {
  local provider llm_url llm_model emb_provider emb_url emb_model
  provider="$(env_get LLM_PROVIDER)"
  [[ "$provider" == "fake" ]] && warn "LLM_PROVIDER=fake 입니다. 실제 모델은 .env.local에서 설정하세요."
  llm_url="$(env_get LLM_BASE_URL)"
  llm_url="${llm_url:-http://host.docker.internal:11434/v1}"
  llm_model="$(env_get LLM_MODEL)"
  emb_provider="$(env_get EMBEDDING_PROVIDER)"
  emb_provider="${emb_provider:-$provider}"
  emb_url="$(env_get EMBEDDING_BASE_URL)"
  emb_url="${emb_url:-$llm_url}"
  emb_model="$(env_get EMBEDDING_MODEL)"
  [[ -n "$llm_model" ]] || fail ".env.local에 LLM_MODEL이 없습니다"

  if [[ "$provider" != "fake" && "$provider" != "bedrock" ]] && is_ollama_url "$llm_url"; then
    ensure_ollama
    ensure_ollama_model "$llm_model"
  fi
  if [[ "$emb_provider" != "fake" && "$emb_provider" != "bedrock" ]] && is_ollama_url "$emb_url"; then
    ensure_ollama
    ensure_ollama_model "${emb_model:-bge-m3}"
  fi
  if [[ "$llm_url" == *"api.openai.com"* || "$emb_url" == *"api.openai.com"* ]]; then
    [[ -n "$(env_get LLM_API_KEY)" ]] || fail "OpenAI API를 쓰려면 .env.local에 LLM_API_KEY가 필요합니다"
    warn "OpenAI API 사용: 질문과 검색된 문서 일부가 OpenAI로 전송됩니다"
  fi
  info "생성: ${provider:-openai_compat} / $llm_model  ·  임베딩: ${emb_provider:-openai_compat} / ${emb_model:-bge-m3}"
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
    cat <<'EOF'

✅ 준비 완료 (.env.local 설정 사용)
  웹:       http://localhost:5173   (아무 이메일로 로그인, 운영 화면은 admin@local.test)
  API:      http://localhost:8000/docs
  로그:     ./scripts/run-local.sh logs
  중지:     ./scripts/run-local.sh down
  설정 변경: .env.local 수정 후 ./scripts/run-local.sh 다시 실행
EOF
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
