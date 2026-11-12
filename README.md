# ETF Agent

ETF 질의응답 AI Agent의 MVP(Phase 1) 모노레포. **로컬 Docker에서 끝까지 돌아가는 상태**가 목표이며,
나중에 Supabase·Cloudflare·AWS로 옮길 때는 **설정(`.env`)과 어댑터만** 바꾸면 되도록 구성했다.

```
질문 → 발화 전처리 → 오케스트레이터(의도 분류·라우팅) → 전문 에이전트(ETF 정보 | 지식·FAQ | 공시 요약)
     → 답변 합성 → 컴플라이언스 가드(룰 → 검증 모델 → 고위험 템플릿) → SSE 스트리밍 응답
```

> 상품·시세·공시·문서는 모두 개발용 **샘플** 데이터다(`data/samples`, 이름·설명에 '샘플' 표기).

## 사전 준비

| 도구 | 용도 | 비고 |
| --- | --- | --- |
| Docker + Compose v2.24+ | db·api·web 실행 | 맥은 Docker Desktop 또는 colima(`colima start`) |
| [uv](https://docs.astral.sh/uv/) | 호스트에서 `make test`·`make lint` | Python 3.14는 uv가 받는다 |
| Node.js 24 (`.nvmrc`) | 호스트에서 `make lint`(eslint·prettier·tsc) | web 컨테이너는 자체 Node 사용 |
| [Ollama](https://ollama.com) (호스트) | LLM·임베딩 | 맥 Docker는 GPU 가속이 안 되므로 **호스트에서 실행** |

### 모델 받기 (자동으로 받지 않는다)

```bash
ollama serve                       # 앱으로 설치했다면 이미 떠 있음
make pull-models                   # = ollama pull bge-m3 (임베딩, 1024차원)
```

생성 모델 기본값은 `LLM_MODEL=midm-2.0-mini`(KT Mi:dm 2.0 Mini)이다. 공식 저장소
[K-intelligence/Midm-2.0-Mini-Instruct](https://huggingface.co/K-intelligence/Midm-2.0-Mini-Instruct/tree/main)
는 safetensors로 배포되며, 작성 시점에 공식 Mini GGUF는 확인하지 못했다(Base 모델은 커뮤니티 GGUF가 있다).
둘 중 하나로 준비한다.

1. **Mi:dm 2.0 Mini GGUF 등록** — Hugging Face에서 커뮤니티 GGUF(`Midm-2.0-Mini-Instruct GGUF` 검색)를 받거나
   llama.cpp의 `convert_hf_to_gguf.py`로 직접 변환한 뒤:
   ```bash
   cp <받은파일>.gguf infra/local/ollama/midm-2.0-mini-instruct-q4_k_m.gguf   # *.gguf는 git 제외
   ollama create midm-2.0-mini -f infra/local/ollama/Modelfile.midm
   ```
2. **대체 모델** — 바로 쓸 수 있는 한국어 가능 모델을 받고 `.env`의 `LLM_MODEL`만 바꾼다.
   ```bash
   ollama pull gemma3:12b        # 또는 exaone3.5:7.8b(비상업 라이선스), qwen3:4b 등
   # .env(.local): LLM_MODEL=gemma3:12b  (JUDGE_MODEL을 비우면 같은 모델로 검증)
   ```
   추론형 모델이 내는 `<think>…</think>`는 어댑터가 제거한다.
   임베딩도 `snowflake-arctic-embed2`(1024차원, 다국어)로 바꿀 수 있다(`EMBEDDING_MODEL`).

맥이 아닌 OS(리눅스·윈도우)는 컨테이너 Ollama를 쓸 수 있다:
`make up-ollama` 후 `.env`에 `LLM_BASE_URL=http://ollama:11434/v1`,
모델은 `docker compose -f infra/local/docker-compose.yml exec ollama ollama pull bge-m3`.

## 실행 순서

```bash
cp .env.example .env              # 최소: POSTGRES_PASSWORD, DATABASE_URL, LOCAL_JWT_SECRET (아래 예시)
make setup                        # (호스트) uv sync + npm ci — test/lint용

make up                           # db·api·web 기동(헬스체크까지 대기)
make migrate && make seed && make ingest
open http://localhost:5173        # 로그인 → 질문

make test                         # LLM_PROVIDER=fake, 별도 <DB>_test DB 사용
make lint                         # ruff + eslint + prettier + tsc
make demo                         # 대표 질문 6개(호스트 Ollama 필요)
make eval                         # 평가 리포트(JSON + 표)
make down                         # 중지(볼륨 유지)
```

Ollama 없이 전체를 돌려 보려면 `PROVIDER=fake`를 붙인다(fake LLM·fake 임베딩).

```bash
make up PROVIDER=fake && make migrate && make seed && make ingest PROVIDER=fake
make demo PROVIDER=fake ; make eval PROVIDER=fake
```

> 임베딩 공급자를 바꾸면(fake ↔ bge-m3) `make ingest`가 모델 이름 차이를 감지해 다시 임베딩한다.
> 같은 문서·같은 모델이면 `unchanged`로 건너뛴다(`ARGS="--force"`로 강제).

### 한 줄 실행 스크립트

```bash
./scripts/run-fake.sh     # Ollama 없이(fake LLM·임베딩). demo | eval | test | down 하위 명령
./scripts/run-local.sh    # .env.local의 실제 모델로(Ollama면 모델 확인·다운로드까지). down | logs
```

두 스크립트 모두 `.env`가 없으면 `.env.example`로 만들고 DB 비밀번호·JWT 키를 무작위로 채운 뒤
기동 → migrate → seed → ingest까지 한다(이미 있는 값은 건드리지 않는다).

### 개인용 로컬 설정 `.env.local` (gitignore)

`.env.local`은 `.env` 뒤에 읽혀 같은 이름의 값을 덮는다(앱 설정·compose·Makefile 모두 같은 순서).
개인 API 키나 모델 선택은 여기에 둔다. `run-local.sh`가 없으면 `.env.local.example`로 만든다.

| 방식 | 설정 | 비고 |
| --- | --- | --- |
| Ollama(기본) | `LLM_MODEL=gemma3:12b`, `EMBEDDING_MODEL=snowflake-arctic-embed2` | 질의가 이 Mac 밖으로 나가지 않는다 |
| OpenAI API | `LLM_BASE_URL=https://api.openai.com/v1`, `LLM_API_KEY`, `EMBEDDING_REQUEST_DIMENSIONS=true` | 질의가 OpenAI로 전송된다. gpt-5·o 계열은 `OPENAI_MAX_TOKENS_PARAM`·`OPENAI_OMIT_TEMPERATURE` |

**일반 대화 모드**(`GENERAL_CHAT_ENABLED=true`, `APP_ENV=local` 전용) — 개인용 ChatGPT처럼 쓴다.

- ETF와 무관한 질문(코딩·일상 등)은 범위 밖 템플릿 대신 모델이 이전 대화를 이어 자유롭게 답한다.
- ETF·투자와 무관한 추천·시점 질문('저녁 메뉴 추천해줘')도 일반 대화로 간다.
- FAQ 질문에 등록 문서 근거가 없으면 모델 일반 지식으로 답하고 '근거 없음'을 표시한다.
- ETF 정보·공시·근거 있는 FAQ, 고위험·ETF 추천 템플릿, 금칙 표현·개인정보 룰 가드는 그대로다.
- 배포(`APP_ENV≠local`)에서는 켤 수 없다(설정 검증에서 기동 실패).

고도화 버전(AWS Bedrock·자체 호스팅 vLLM)은 [`infra/aws/README.md`](infra/aws/README.md)를 본다.

### 로컬 .env 예시

```dotenv
APP_ENV=local
POSTGRES_USER=etf
POSTGRES_PASSWORD=<openssl rand -hex 16>
POSTGRES_DB=etf_agent
DATABASE_URL=postgresql+asyncpg://etf:<위 비밀번호>@db:5432/etf_agent
LOCAL_JWT_SECRET=<openssl rand -hex 32>
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_MODEL=midm-2.0-mini
```

### 브라우저 사용

- `http://localhost:5173` → 이메일만 입력(dev-login, `APP_ENV=local`에서만 열림)
- 질문하면 진행 상태(`질문을 이해하는 중` → `ETF 정보를 찾는 중` …) → 토큰 스트리밍 → 출처·고지 → 👍/👎/정정
- 설명 수준(입문·중급·숙련) 선택, 대화 목록(멀티턴, 최근 `HISTORY_TURNS`턴)
- `admin@local.test`(`ADMIN_EMAILS`)로 로그인하면 상단 **운영** 탭: 트레이스(의도·가드 필터), 피드백, 문서 업로드 → ingest → 검색 확인

### make 타깃

| 타깃 | 설명 |
| --- | --- |
| `up` / `down` / `ps` / `logs` | 로컬 스택(db·api·web). api는 `--reload`, web은 Vite dev server |
| `up-ollama` | 컨테이너 Ollama 포함(`ollama` 프로필) |
| `migrate` / `seed` / `ingest` / `collect` | Alembic, 샘플 적재, 문서 적재(`ARGS="경로 --force"`), 공공데이터·DART 수집 |
| `test` / `lint` / `fmt` | 호스트에서 실행 |
| `eval` / `demo` | api 컨테이너에서 실행. `PROVIDER=fake` 지원, eval은 `ARGS="--with-judge --out r.json"` |
| `pull-models` | 호스트 Ollama에 `.env`(`.local`)의 `EMBEDDING_MODEL`·`LLM_MODEL` 받기 |

## API 요약

| 메서드·경로 | 인증 | 설명 |
| --- | --- | --- |
| `GET /health` | - | DB 확인(실패 시 503) |
| `POST /auth/dev-login` | - | `{email}` → JWT. `APP_ENV=local`·`AUTH_PROVIDER=local`에서만 |
| `GET /auth/me` | 사용자 | 현재 사용자 |
| `POST /chat` | 사용자 | SSE. 본문 `{message, conversation_id?, level}` |
| `GET /history`, `GET /history/{id}` | 사용자 | 대화 목록·메시지 |
| `POST /feedback` | 사용자 | `{kind: like\|dislike\|correction, message_id, correction_text?}` |
| `GET /admin/traces?intent=&verdict=` | admin | 트레이스(질의 원문 없음) |
| `GET /admin/feedback`, `GET/POST /admin/documents`, `GET /admin/search?q=` | admin | 피드백, 문서 목록·업로드(ingest), 검색 확인 |
| `GET /metrics` | - | Prometheus 형식 |

**SSE 이벤트 순서**: `status`(요청 즉시) → `status`… → `token`… → `sources` → `done`
(`done`: `request_id`, `conversation_id`, `message_id`, `intents`, `guard{verdict, reasons}`, `latency_ms`).
헤더 `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

**가드 판정(`verdict`)**: `pass` · `pass_after_retry`(1회 재생성 후 통과) · `blocked`(재생성 후에도 실패 → 안전 답변) ·
`template`(고위험·추천·범위 밖 고정 답변) · `llm_unavailable`(LLM 실패, 폴백 없음 → 안전 답변) · `error`

## 환경변수

정의는 `apps/api/app/settings.py`가 단일 출처다. 빈 값은 기본값이고, 우선순위는 셸 환경변수 > `.env.local` > `.env`.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `APP_ENV` | `local` | `local` \| `dev` \| `prod`. local: 콘솔 로그·dev-login 허용 |
| `LOG_LEVEL` | `INFO` | |
| `CORS_ORIGINS` | `http://localhost:5173` | 쉼표 구분 |
| `DATABASE_URL` | **필수** | `postgresql+asyncpg://…@db:5432/…` |
| `POSTGRES_USER/PASSWORD/DB/PORT` | `etf`/-/`etf_agent`/`5432` | 로컬 db 컨테이너 |
| `TEST_DATABASE_URL` | `POSTGRES_*`로 조합 | `make test`. DB 이름 뒤에 `_test`를 붙인 DB를 새로 만든다 |
| `AUTH_PROVIDER` | `local` | `local` \| `supabase`(스텁) \| `cognito`(스텁) |
| `ADMIN_AUTH` | `local` | `local`(role=admin) \| `cf_access`(스텁) |
| `LOCAL_JWT_SECRET` | local에서만 임의 생성 | local JWT 서명 키. local 외 환경에서는 필수 |
| `LOCAL_JWT_TTL_MINUTES` | `720` | |
| `ADMIN_EMAILS` | `admin@local.test` | dev-login 시 admin 역할 부여 |
| `SUPABASE_URL` / `SUPABASE_JWKS_URL` / `SUPABASE_JWT_SECRET` | - | [나중] Supabase Auth |
| `COGNITO_USER_POOL_ID` / `COGNITO_REGION` | - / `ap-northeast-2` | [나중] Cognito |
| `CF_ACCESS_TEAM_DOMAIN` / `CF_ACCESS_AUD` | - | [나중] Cloudflare Access |
| `LLM_PROVIDER` | `openai_compat` | `openai_compat`(Ollama·vLLM·OpenAI API) \| `bedrock` \| `fake` |
| `LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | OpenAI 호환 `/v1` |
| `LLM_API_KEY` | - | OpenAI API 키(`.env.local`에만), vLLM `--api-key` |
| `LLM_MODEL` | `midm-2.0-mini` | 생성 모델(bedrock이면 모델 ID·추론 프로필 ID) |
| `JUDGE_MODEL` | = `LLM_MODEL` | 검증 모델 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_TOKENS` / `LLM_TEMPERATURE` | `60` / `800` / `0.2` | |
| `OPENAI_MAX_TOKENS_PARAM` / `OPENAI_OMIT_TEMPERATURE` | `max_tokens` / `false` | OpenAI gpt-5·o 계열: `max_completion_tokens` / `true` |
| `EMBEDDING_PROVIDER` | = `LLM_PROVIDER` | `openai_compat` \| `bedrock` \| `fake` |
| `EMBEDDING_BASE_URL` | = `LLM_BASE_URL` | |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `bge-m3` / `1024` | 차원은 `chunks.embedding` 컬럼과 일치. bedrock: `amazon.titan-embed-text-v2:0` |
| `EMBEDDING_REQUEST_DIMENSIONS` | `false` | 임베딩 요청에 `dimensions` 전송(OpenAI text-embedding-3) |
| `BEDROCK_REGION` / `BEDROCK_PROFILE` | `ap-northeast-2` / - | Bedrock 리전, (로컬 시험용) `~/.aws` 프로필. 자격 증명은 boto3 기본 체인 |
| `FALLBACK_PROVIDER` | `none` | `none` \| `bedrock` |
| `BEDROCK_MODEL_ID` / `FALLBACK_ALLOWED_INTENTS` | - / `faq` | 폴백 모델 ID(bedrock이면 필수), 폴백 허용 의도 |
| `STORAGE_PROVIDER` | `local` | `local` \| `supabase`(스텁) \| `s3`(스텁) |
| `STORAGE_LOCAL_DIR` | `var/storage` (compose: `/data/storage` 볼륨) | |
| `TRACER` | `pg` | `pg` \| `langfuse`(스텁) |
| `HISTORY_TURNS` | `4` | 멀티턴 최근 N턴 |
| `STREAM_TOKEN_DELAY_MS` | `0` | 토큰 이벤트 간 지연(타이핑 효과) |
| `RAG_TOP_K` / `RAG_VECTOR_WEIGHT` / `RAG_MIN_SCORE` | `4` / `0.7` / `0.25` | 하이브리드 검색 상위 k, 벡터 가중치, 근거 최소 점수 |
| `ENTITY_FUZZY_THRESHOLD` | `80` | ETF명 오타 허용 기준(rapidfuzz) |
| `INQUIRY_CHANNEL` | 샘플 고객센터 문구 | 안전 답변·고위험 템플릿의 문의 채널 |
| `GENERAL_CHAT_ENABLED` / `GENERAL_CHAT_TEMPERATURE` | `false` / `0.7` | 일반 대화 모드(`APP_ENV=local` 전용) |
| `DATA_GO_KR_API_KEY` / `DART_API_KEY` | - | 없으면 `make collect`가 안내만 출력 |
| `EXTERNAL_TIMEOUT_SECONDS` | `15` | 공공데이터·DART 타임아웃 |
| `VITE_API_BASE_URL` | `http://localhost:8000` | web(compose가 주입) |
| `VITE_AUTH_MODE` | `local` | `local` \| `supabase`(미구현) |

## 기능 ID ↔ 코드 위치

| 기능 ID | 내용 | 코드 |
| --- | --- | --- |
| P1-DA-01 | DB 스키마(pgvector·pg_trgm, HNSW·trgm 인덱스) | `apps/api/app/repositories/models.py`, `apps/api/migrations/versions/20261112_0002_core_schema.py`, `infra/local/db/init.sql` |
| P1-DA-02 | 샘플 시드, 공공데이터포털·DART 수집 | `jobs/seed/`, `jobs/collector/`, `data/samples/` |
| P1-DA-03 | 문서 ingest(문단 청킹·겹침, 재적재 갱신) | `apps/api/app/rag/ingest.py`, `apps/api/app/rag/chunker.py`, `jobs/ingest/` |
| P1-AG-01 | 발화 전처리·ETF명 인식(rapidfuzz) | `apps/api/app/agents/preprocess/` |
| P1-AG-02 | 오케스트레이터(LLM JSON → 키워드 규칙, 병렬 라우팅), 일반 대화(로컬 전용) | `apps/api/app/agents/orchestrator/`, `apps/api/app/agents/graph.py`, `apps/api/app/agents/general/` |
| P1-AG-03 | ETF 정보 에이전트·도구 | `apps/api/app/agents/etf_info/`, `apps/api/app/tools/{etf_search,price_lookup,compare}.py` |
| P1-AG-04 | 지식·FAQ 에이전트(하이브리드 검색, 수준별) | `apps/api/app/agents/faq/`, `apps/api/app/rag/retriever.py`, `prompts/system/faq_*.md` |
| P1-AG-05 | 공시 요약 에이전트 | `apps/api/app/agents/disclosure/`, `apps/api/app/tools/disclosure_lookup.py` |
| P1-AG-06 | 답변 합성·컴플라이언스 가드·폴백 자리 | `apps/api/app/agents/compose/`, `apps/api/app/agents/guard/`, `prompts/guard/`, `prompts/templates/`, `apps/api/app/llm/{router,bedrock}.py`, `apps/api/app/privacy/` |
| P1-API-01 | dev-login, `/chat` SSE | `apps/api/app/routers/{auth,chat}.py`, `apps/api/app/services/chat.py`, `apps/api/app/auth/` |
| P1-API-02 | 이력 | `apps/api/app/routers/history.py` |
| P1-API-03 | 피드백 | `apps/api/app/routers/feedback.py` |
| P1-API-04 | 운영 API(트레이스·피드백·업로드) | `apps/api/app/routers/admin.py`, `apps/api/app/deps.py`(require_admin), `apps/api/app/storage/` |
| P1-API-05 | 캐시 | `apps/api/app/cache/__init__.py` |
| P1-FE-01 | 로그인·대화 목록·채팅 | `apps/web/src/components/{Login,ChatView}.tsx`, `apps/web/src/lib/` |
| P1-FE-02 | 상태·스트리밍·출처·고지·피드백·수준 선택 | `apps/web/src/components/{MessageView,Markdown}.tsx` |
| P1-FE-03 | 운영 화면 | `apps/web/src/components/AdminView.tsx` |
| P1-OP-01 | pg 트레이서(요청당 1행, 원문 없음) | `apps/api/app/observability/pg_tracer.py` |
| P1-OP-02 | `/metrics` | `apps/api/app/observability/metrics.py`, `apps/api/app/main.py`(미들웨어) |
| P1-OP-03 | 평가 CLI·데모 | `ml/eval/`, `data/eval-sets/`, `scripts/demo.py` |

테스트: `apps/api/tests/` — 의도별 경로(`test_graph_routes.py`), SSE 순서·첫 status 즉시성(`test_chat_api.py`),
금칙 표현·1회 재생성 후 안전 답변(`test_guard.py`), 트레이스 원문 미저장(`test_traces.py`), 오타·별칭 인식(`test_preprocess.py`),
Bedrock 요청 형식·폴백·SDK import 경계(`test_bedrock.py`), 일반 대화 모드(`test_general_chat.py`).

## 확장 지점 (배포 시 바꿀 설정·어댑터)

| 영역 | 지금(로컬) | 나중 | 바꿀 설정 | 구현할 파일 |
| --- | --- | --- | --- | --- |
| DB | 로컬 Postgres 컨테이너 | Supabase(Session pooler 5432) → RDS | `DATABASE_URL` | 없음(마이그레이션이 `extensions` 스키마를 자동 감지) |
| 인증 | local JWT(dev-login) | Supabase Auth → Cognito | `AUTH_PROVIDER`, `SUPABASE_*`/`COGNITO_*` | `app/auth/supabase_jwt.py`, `app/auth/cognito_jwt.py`, web `src/lib/auth.ts` |
| 운영 화면 인증 | role=admin | Cloudflare Access | `ADMIN_AUTH=cf_access`, `CF_ACCESS_*` | `app/auth/cf_access.py` |
| 파일 저장 | 로컬 볼륨 | Supabase Storage → S3 | `STORAGE_PROVIDER` | `app/storage/supabase_storage.py`, `app/storage/s3.py` |
| LLM | Ollama(OpenAI 호환) | **Bedrock** 또는 AWS 자체 호스팅 vLLM | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL` (`infra/aws/`) | 없음(구현됨: `app/llm/bedrock.py`) |
| 임베딩 | Ollama bge-m3 등 | Bedrock Titan v2 | `EMBEDDING_PROVIDER=bedrock`, `EMBEDDING_MODEL` | 없음(구현됨) |
| 폴백 | 없음 | Bedrock | `FALLBACK_PROVIDER=bedrock`, `BEDROCK_MODEL_ID` | 없음(구현됨) |
| 트레이스 | Postgres `traces` | Langfuse | `TRACER=langfuse` | `app/observability/langfuse_tracer.py` |
| 메트릭 | `/metrics` 노출 | Grafana Cloud 수집 | — | 없음(수집기 설정만) |
| 캐시 | 프로세스 TTLCache | (필요 시) Redis | — | `app/cache/__init__.py`(함수 시그니처 유지) |

스텁은 모두 인터페이스를 구현하고 `NotImplementedError`를 던진다(API는 501로 응답).
에이전트·도구·RAG(`agents/`, `tools/`, `rag/`)는 공급자 SDK를 import 하지 않는다.

## 캐시 키 규칙 (cachetools TTLCache, 프로세스 단위)

| 키 | TTL | 내용 |
| --- | --- | --- |
| `etf_master:all` | 1일 | 이름·별칭 사전(전처리) |
| `etf:{ticker}` | 1일 | ETF 마스터 단건 |
| `price:latest:{ticker}` | 1시간 | 최신 일별 시세 |
| `faq:{level}:{sha256(정규화 질문)[:16]}` | 1시간 | **가드를 통과한** FAQ 답변. 이전 대화가 있는 질문·재생성 시도는 캐시하지 않음 |

`make seed`·`make collect`는 전체를, ingest(업로드 포함)는 FAQ 캐시를 비운다. 키에는 질문 원문 대신 해시만 쓴다.

## 디렉토리

```
apps/api/app/   main.py settings.py db.py logging.py container.py deps.py
                routers/ agents/ tools/ llm/ rag/ repositories/ auth/ storage/ observability/ cache/ privacy/ services/
apps/api/       migrations/ tests/ pyproject.toml Dockerfile(빌드 컨텍스트: 레포 루트)
apps/web/       Vite + React + TS
jobs/           seed/ collector/ ingest/
ml/eval/        평가 CLI
prompts/        system/ guard/(rules.yaml, disclaimers.yaml, judge.md) templates/(high_risk/*.md 등)
data/           samples/(시드·문서) eval-sets/(형식 예시 10줄씩)
infra/local/    docker-compose.yml db/init.sql ollama/Modelfile.midm
infra/aws/      고도화 버전 설정 예시(Bedrock, 자체 호스팅 vLLM, IAM 최소 권한)
infra/mvp/      (참고) 이전 EC2 + cloudflared 배포 초안 — 이번 범위에서는 쓰지 않는다
scripts/        demo.py run-fake.sh run-local.sh _common.sh
```

## 결정 기록

| 날짜 | 결정 | 이유 |
| --- | --- | --- |
| 2026-11-11 | Python 3.14, 의존성 `==` 고정 + `uv.lock` | 재현성 우선. 업데이트는 `uv lock --upgrade` |
| 2026-11-11 | Postgres 이미지 `pgvector/pgvector:0.8.7-pg17-trixie`, 확장은 `extensions` 스키마가 있으면 그곳에 | Supabase 메이저 버전·권장 방식에 맞춘다 |
| 2026-11-11 | `DATABASE_URL`은 asyncpg만, Supabase는 Session pooler(5432) | Transaction pooler는 asyncpg prepared statement와 충돌 |
| 2026-11-11 | 설정은 `env_ignore_empty=True`, 목록 값은 쉼표 구분 | `.env.example`을 그대로 복사해도 기본값으로 동작 |
| 2026-11-11 | 호스트 포트는 `127.0.0.1`에만 바인딩 | 로컬 개발 전용 |
| 2026-11-12 | CI 워크플로(`.github/workflows/ci.yml`) 삭제 | 이번 범위에서 CI/CD 제외(요구사항) |
| 2026-11-12 | 로컬 스택을 `infra/local`로 새로 만들고 db 서비스명 `db`(+ 네트워크 별칭 `postgres`) | 요구 구조를 따르면서 예전 `.env`의 `@postgres:5432`도 그대로 동작 |
| 2026-11-12 | api 이미지 빌드 컨텍스트를 레포 루트로, 컨테이너도 `/workspace`에 레포 구조 그대로 | prompts·jobs·data·ml을 같은 상대 경로로 쓰고, 호스트·컨테이너의 ingest `source_uri`가 같아진다 |
| 2026-11-12 | dev 모드는 레포 전체 바인드 마운트 + `uvicorn --reload`(app·prompts 감시) | 코드·프롬프트 수정이 바로 반영 |
| 2026-11-12 | web 컨테이너는 `node_modules`를 전용 볼륨으로 두고 기동 시 `npm ci` | 호스트(macOS) 네이티브 바이너리와 섞이지 않게 |
| 2026-11-12 | 기본값을 로컬 어댑터로(`AUTH=local`, `STORAGE=local`, `FALLBACK=none`, `TRACER=pg`) | `.env`를 거의 비워도 로컬에서 동작 |
| 2026-11-12 | `LOCAL_JWT_SECRET`이 없으면 local 환경에서만 임의 생성, 그 외 환경은 기동 실패 | 키를 하드코딩하지 않으면서 첫 실행 마찰을 줄인다(재시작 시 재로그인 필요) |
| 2026-11-12 | `admin@local.test`를 기본 admin 이메일로 | dev-login은 이메일만 받으므로 역할은 설정으로 정한다 |
| 2026-11-12 | 기본 LLM `midm-2.0-mini`(Ollama 로컬 모델명), GGUF 미확보 시 `qwen3:4b` 등으로 교체 | 공식 Mini GGUF를 확인하지 못해 Modelfile 등록 방식과 대체 경로를 함께 둔다 |
| 2026-11-12 | `EMBEDDING_PROVIDER`를 따로 둠(기본은 `LLM_PROVIDER`), 문서에 `embedding_model` 저장 | 임베딩 모델이 바뀌면 재임베딩을 감지하고, fake/실제 벡터가 섞이지 않게 |
| 2026-11-12 | fake LLM의 분류 응답은 일부러 비-JSON | 키 없는 환경·테스트에서 키워드 규칙 대체 경로가 기본이 되고, JSON 경로는 스크립트 응답으로 테스트 |
| 2026-11-12 | LangGraph로 그래프 구성, 복수 의도는 조건부 분기로 병렬 실행 후 compose에서 합류 | 이미 의존성에 있고 superstep 병렬·재시도 루프를 선언적으로 표현할 수 있다 |
| 2026-11-12 | 고위험 > 추천 > 나머지 순서로 배타 처리, 고위험 키워드 규칙은 LLM 결과와 무관하게 항상 적용 | 분류 모델이 놓쳐도 고위험 질문이 생성 경로로 가지 않게 |
| 2026-11-12 | 고위험이 섞인 복합 질문은 템플릿만 답한다 | 일부라도 생성하면 권유로 읽힐 수 있다(보수적 선택) |
| 2026-11-12 | 답변 합성은 LLM 재작성 없이 섹션 결합 + 고지 | DB 수치·출처가 합성 단계에서 바뀌지 않게 |
| 2026-11-12 | ETF 정보·공시는 DB 표·목록이 본문이고 LLM은 1~2문장 요약만, LLM 실패 시 요약 없이 답한다 | "숫자는 DB 값만" 원칙. Ollama가 없어도 정보 조회는 동작 |
| 2026-11-12 | 재생성 시도에서는 ETF·공시 요약 문장을 빼고 DB 내용만 낸다 | 수치 오류의 원인이 요약 문장뿐이라 재생성 성공률이 높다 |
| 2026-11-12 | 토큰은 가드 통과 후 최종 답변을 단어 단위로 나눠 스트리밍 | 검증 전 문장이 화면에 노출되지 않게(준법 우선). 체감 지연은 status 이벤트로 보완 |
| 2026-11-12 | 답변 저장·트레이스는 토큰 전송 전에 기록 | 클라이언트가 중간에 끊어도 기록이 남는다 |
| 2026-11-12 | 룰에서 걸리면 검증 모델을 부르지 않고, DB 표·목록만 있는 답변은 검증 모델을 생략 | 지연·비용 절감. 판정 대상은 LLM 생성 문장 |
| 2026-11-12 | 검증 모델 JSON 파싱 실패·호출 실패는 통과(사유 `note:judge_*` 기록) | 룰은 이미 통과했고, 작은 로컬 모델의 형식 오류로 정상 답변이 막히는 것을 피한다. 운영 화면에서 추적 가능 |
| 2026-11-12 | 근거 없는 수치 검사는 단위(%·원·배 등)가 붙거나 소수인 수치만, 날짜·티커·인용 번호 제외 | 일반 숫자까지 보면 오탐이 많다 |
| 2026-11-12 | 금칙 표현은 고지 영역을 뺀 본문에만 적용하고, 부정형은 부정 전방탐색으로 제외 | "원금이 보장되지 않습니다" 같은 고지·설명이 걸리지 않게 |
| 2026-11-12 | 트레이스 `intent`는 복수 의도를 `+`로 이어 저장, 필터는 배열 분해로 | 지정된 컬럼 목록을 유지하면서 복수 의도 필터 지원 |
| 2026-11-12 | `etf_master.alias_text`(이름+별칭) 컬럼을 앱이 유지하고 trgm 인덱스 | 배열 컬럼은 trgm 인덱스를 바로 걸 수 없다(immutable 함수 필요) |
| 2026-11-12 | 하이브리드 점수 = 0.7×코사인 + 0.3×`word_similarity`, 근거 최소 점수 0.25 | 짧은 한국어 질의는 `similarity`보다 `word_similarity`가 맞다. 값은 설정으로 조정 |
| 2026-11-12 | 업로드 문서 키는 `uploads/{파일명}` | 같은 파일명을 다시 올리면 같은 문서로 갱신된다 |
| 2026-11-12 | 마크다운은 의존성 없이 최소 렌더러로 표시 | 표·링크·목록만 필요하고, innerHTML을 쓰지 않아 XSS 위험이 없다 |
| 2026-11-12 | 테스트는 `<DB>_test`를 세션마다 새로 만들어 마이그레이션·시드·ingest | 개발 DB를 오염시키지 않고 마이그레이션까지 검증 |
| 2026-11-12 | ruff `E501` 끔 | 코드 줄은 formatter가 맞추고, 한글 주석은 폭 계산 때문에 오탐이 많다 |
| 2026-11-12 | Makefile은 `-include .env` 대신 필요한 값만 `?=`로 읽음 | `-include`가 셸의 `LLM_PROVIDER=fake`를 빈 값으로 덮어쓰는 문제 |
| 2026-11-12 | `boto3`·`sse-starlette` 의존성 제거, `rapidfuzz`·`pyyaml`·`prometheus-client`·`python-multipart` 추가 | 폴백 미구현이라 boto3 불필요, SSE는 StreamingResponse로 충분 |
| 2026-11-12 | 샘플 종목코드는 실존하지 않는 `9000x0`, 운용사도 가상 이름 | 실제 상품으로 오인되지 않게 |
| 2026-11-12 | 고도화 버전 LLM은 AWS(Bedrock 관리형 또는 자체 호스팅 vLLM), 로컬은 Ollama | 소형 로컬 모델보다 품질이 높고 모델 출처를 고를 수 있다. 외부 API 금지 정책이면 vLLM 자체 호스팅 |
| 2026-11-12 | `boto3` 다시 추가, `llm/bedrock.py`에서만 import. 생성은 Converse API, 임베딩은 Titan v2·Cohere | 모델 공통 형식이라 모델 ID만 바꿔 쓴다. DB 1024차원 그대로 |
| 2026-11-12 | Bedrock 자격 증명은 boto3 기본 체인만, 프로필 설정은 `BEDROCK_PROFILE` | 키를 설정에 두지 않는다. 빈 `AWS_PROFILE`이 컨테이너에 들어가 boto3가 깨지는 것을 피한다 |
| 2026-11-12 | 개인 설정은 `.env.local`(gitignore)로 분리, `.env` 뒤에 읽음 | 공용 `.env`를 건드리지 않고 개인 키·모델을 바꾼다 |
| 2026-11-12 | 테스트는 dotenv 파일을 읽지 않는다 | 개인 `.env.local` 값이 테스트 결과를 바꾸지 않게 |
| 2026-11-12 | 일반 대화 모드는 `APP_ENV=local`에서만, 고위험·ETF 추천 템플릿과 금칙·개인정보 룰은 유지 | 개인용으로 열되 배포 서비스의 준법 경로는 바뀌지 않게 |
| 2026-11-12 | 일반 대화는 정규화본 대신 원문을 모델에 보낸다 | 정규화가 기호·줄바꿈을 지워 코드·서식이 깨진다. 원문은 메모리에서만 쓰고 저장은 마스킹본 |
| 2026-11-12 | 근거 없는 답변(일반 대화)은 수치 대조·검증 모델을 건너뛴다 | 대조할 근거가 없어 모든 수치가 오탐이 된다. 금칙 표현·개인정보 룰은 적용 |
