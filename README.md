# ETF Agent

ETF 질의응답 AI Agent의 MVP(Phase 1) 모노레포.

## 개요

| 영역 | MVP(Phase 1) | Phase 2 |
| --- | --- | --- |
| 프런트 | Vite + React + TS 정적 SPA → Cloudflare Pages | 동일 |
| 서버 | FastAPI 1개, EC2에서 Docker Compose 실행, cloudflared로 노출 | 동일 |
| DB | Supabase(서울) Postgres + pgvector | RDS |
| 인증 | Supabase Auth | Cognito |
| 파일 | Supabase Storage | S3 |
| LLM | Ollama(OpenAI 호환 API), 폴백 Amazon Bedrock(ap-northeast-2) | vLLM |

Phase 2 전환 시 바뀌는 것은 **설정(`.env`)과 어댑터(`app/auth`, `app/storage`, `app/llm`, `app/observability`)뿐**이어야 한다.
서버는 DB를 SQLAlchemy로만 다루며 supabase-py·Supabase REST로 데이터에 접근하지 않는다.

## 사전 준비

- Docker (Compose v2.24 이상)
- [uv](https://docs.astral.sh/uv/) — Python 3.14는 uv가 자동으로 받는다
- Node.js 24 LTS (`.nvmrc`)
- (선택) 네이티브 [Ollama](https://ollama.com) — 맥에서는 컨테이너보다 빠르다
- pre-commit: `uv tool install pre-commit`

## 실행 방법

```bash
cp .env.example .env            # 값 채우기 (아래 "로컬 .env 예시" 참고)
make setup                      # uv sync, npm ci, pre-commit install

make dev                        # api + postgres(dev 프로필) 기동, healthy까지 대기
curl localhost:8000/health      # {"status":"ok","db":"ok"}
make migrate                    # Alembic head 적용(pgvector extension 생성)

make test                       # API 테스트(로컬 postgres 사용)
make lint                       # ruff + eslint + prettier
make fmt                        # 자동 포맷
make web-dev                    # Vite 개발 서버(http://localhost:5173)
make web-build                  # apps/web/dist 생성
make down                       # 컨테이너 중지(볼륨 유지)
```

`make help`로 전체 타깃을 볼 수 있다. 컨테이너 Ollama가 필요하면 `make dev-llm`.

### 로컬 .env 예시

비밀번호는 직접 생성한다(예: `openssl rand -hex 16`). compose 내부에서 api는 `postgres` 호스트로 접속하고,
`make test`는 같은 값으로 `localhost` URL을 조합한다.

```dotenv
APP_ENV=local
CORS_ORIGINS=http://localhost:5173
POSTGRES_USER=etf
POSTGRES_PASSWORD=<생성한 값>
POSTGRES_DB=etf_agent
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://etf:<생성한 값>@postgres:5432/etf_agent
LLM_BASE_URL=http://host.docker.internal:11434/v1
```

### EC2 배포(MVP)

```bash
# .env: DATABASE_URL=Supabase Session pooler URL, CLOUDFLARE_TUNNEL_TOKEN 등
docker compose -f infra/mvp/docker-compose.yml --env-file .env up -d --build   # api + cloudflared
docker compose -f infra/mvp/docker-compose.yml --env-file .env run --rm --no-deps api alembic upgrade head
```

터널 ingress는 Zero Trust 대시보드에서 `http://api:8000`으로 설정한다. 로컬 관리 터널을 쓰려면
`infra/mvp/cloudflared/config.example.yml` 참고.

### 웹 환경변수

`apps/web/.env.example`을 `apps/web/.env.local`로 복사한다. `VITE_` 변수는 번들에 포함되므로 공개 가능한 값만 둔다.

| 변수 | 설명 |
| --- | --- |
| `VITE_API_BASE_URL` | FastAPI 베이스 URL |
| `VITE_SUPABASE_URL` | Supabase 프로젝트 URL |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon(publishable) 키 |

## 환경변수

정의는 `apps/api/app/settings.py`가 단일 출처다. 빈 값은 기본값으로 처리된다.

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `APP_ENV` | | `local` | `local` \| `dev` \| `prod`. `local`은 콘솔 로그, 나머지는 JSON 로그 |
| `LOG_LEVEL` | | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `CORS_ORIGINS` | | `http://localhost:5173` | 허용 오리진, 쉼표 구분 |
| `DATABASE_URL` | ✅ | — | `postgresql+asyncpg://...` |
| `SUPABASE_URL` | | — | Supabase 프로젝트 URL |
| `SUPABASE_JWKS_URL` | | `SUPABASE_URL`에서 유도 | JWT 서명 JWKS URL |
| `SUPABASE_JWT_SECRET` | | — | (선택) 레거시 HS256 시크릿 |
| `LLM_PROVIDER` | | `openai_compat` | `openai_compat` \| `fake` |
| `LLM_BASE_URL` | | `http://localhost:11434/v1` | OpenAI 호환 API 베이스 URL |
| `LLM_API_KEY` | | — | (선택) OpenAI 호환 API 키 |
| `LLM_MODEL` | | `qwen3:8b` | 답변 생성 모델 |
| `JUDGE_MODEL` | | `qwen3:8b` | LLM-as-judge 모델 |
| `EMBEDDING_MODEL` | | `bge-m3` | 임베딩 모델 |
| `EMBEDDING_DIM` | | `1024` | 임베딩 차원(pgvector 컬럼과 일치) |
| `FALLBACK_PROVIDER` | | `bedrock` | `bedrock` \| `none` |
| `BEDROCK_REGION` | | `ap-northeast-2` | Bedrock 리전 |
| `BEDROCK_MODEL_ID` | | — | Bedrock 모델/추론 프로파일 ID |
| `FALLBACK_ALLOWED_INTENTS` | | `faq` | 폴백 허용 의도, 쉼표 구분 |
| `AUTH_PROVIDER` | | `supabase` | `supabase` \| `cognito` |
| `STORAGE_PROVIDER` | | `supabase` | `supabase` \| `s3` |
| `TRACER` | | `pg` | `pg` \| `langfuse` |
| `CF_ACCESS_TEAM_DOMAIN` | | — | Cloudflare Access 팀 도메인 |
| `CF_ACCESS_AUD` | | — | Cloudflare Access AUD 태그 |
| `DATA_GO_KR_API_KEY` | | — | 공공데이터포털 서비스 키 |
| `DART_API_KEY` | | — | DART 오픈API 키 |

인프라·도구 전용(앱 설정 아님):

| 변수 | 사용처 | 설명 |
| --- | --- | --- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_PORT` | compose dev 프로필, `make test` | 로컬 pgvector 컨테이너 |
| `TEST_DATABASE_URL` | `make test` | 비우면 `POSTGRES_*`로 localhost URL 조합 |
| `CLOUDFLARE_TUNNEL_TOKEN` | compose `cloudflared` | 원격 관리 터널 토큰 |

Bedrock 자격증명은 `.env`에 두지 않는다. EC2는 인스턴스 역할, 로컬은 셸의 `AWS_PROFILE`을 쓴다.

## 디렉토리

```
apps/
  web/                 Vite + React + TS SPA (Cloudflare Pages)
  api/                 FastAPI 서버
    app/
      main.py          앱 팩토리, CORS, /health
      settings.py      모든 환경변수(pydantic-settings)
      db.py            async 엔진·세션, FastAPI 의존성, ORM Base
      logging.py       structlog 설정
      routers/         HTTP 라우터
      agents/          LangGraph 에이전트
      tools/           에이전트 도구
      llm/             LLM 어댑터(OpenAI 호환·Bedrock·fake)
      rag/             청킹·임베딩·벡터 검색
      repositories/    SQLAlchemy 데이터 접근
      auth/            인증 어댑터(Supabase/Cognito)
      storage/         파일 저장소 어댑터(Supabase/S3)
      observability/   트레이서 어댑터(pg/Langfuse)
      cache/           인메모리 캐시
      privacy/         개인정보 마스킹·보존
    migrations/        Alembic(async env)
    tests/
jobs/collector/        외부 데이터 수집 배치
jobs/ingest/           문서 파싱·임베딩 적재 배치
ml/finetune/           파인튜닝
ml/eval/               오프라인 평가
prompts/               프롬프트 템플릿
data/eval-sets/        평가 세트
infra/mvp/             docker-compose.yml, cloudflared 예시 설정
.github/               CI, PR 템플릿
```

## 결정 기록

| 날짜 | 결정 | 이유 |
| --- | --- | --- |
| 2026-11-11 | Python 3.14 | 3.15는 막 출시돼 휠 생태계가 덜 갖춰졌고, 3.14는 1년간 안정화됐다 |
| 2026-11-11 | 의존성 `==` 고정 + `uv.lock` 커밋, `package = false` | 라이브러리가 아닌 애플리케이션이라 재현성이 우선이다. 업데이트는 `uv lock --upgrade`로 PR을 만든다 |
| 2026-11-11 | 로컬·CI Postgres는 `pgvector/pgvector:0.8.7-pg17` | Supabase 프로젝트의 Postgres 메이저 버전에 맞춘다. Supabase가 올라가면 함께 올린다 |
| 2026-11-11 | pgvector는 `extensions` 스키마가 있으면 그곳에 생성 | Supabase 권장 방식이다. 로컬과 CI에는 그 스키마가 없어 기본 스키마에 생성한다 |
| 2026-11-11 | `DATABASE_URL`은 asyncpg 스킴만 허용, Supabase는 Session pooler(5432) 또는 direct 연결 사용 | Transaction pooler(6543)는 asyncpg의 prepared statement와 충돌한다 |
| 2026-11-11 | 설정은 `env_ignore_empty=True`, 목록 값은 쉼표 구분 | `.env.example`을 그대로 복사해도 기본값으로 동작하고, 목록을 JSON으로 쓰는 것보다 읽기 쉽다 |
| 2026-11-11 | `LLM_API_KEY`(선택) 추가 | Ollama는 키가 필요 없지만 Phase 2 vLLM의 `--api-key`에 대비한다 |
| 2026-11-11 | 기본 모델 `qwen3:8b` / 임베딩 `bge-m3` | bge-m3는 다국어(한국어) 모델이고 1024차원이라 `EMBEDDING_DIM`과 맞는다. LLM 기본값은 자리표시이며 평가 후 교체한다 |
| 2026-11-11 | `SUPABASE_JWKS_URL`을 비우면 `SUPABASE_URL`에서 유도 | 설정 누락을 줄인다 |
| 2026-11-11 | `/health`는 DB 실패 시 503 `degraded`, DB 체크 타임아웃 2초 | compose·로드밸런서 헬스체크가 DB 장애를 감지할 수 있다 |
| 2026-11-11 | compose에서 `${VAR:?}` 필수 검사를 쓰지 않음 | compose는 프로필과 무관하게 파일 전체를 보간한다. 쓰면 로컬은 터널 토큰이, EC2는 `POSTGRES_*`가 없다는 이유로 실패한다 |
| 2026-11-11 | 호스트 포트는 `127.0.0.1`에만 바인딩 | 외부 노출은 cloudflared가 전담한다 |
| 2026-11-11 | cloudflared는 토큰 기반 원격 관리 터널 | 자격증명 파일을 서버에 둘 필요가 없다. 로컬 관리 방식은 예시 설정으로만 둔다 |
| 2026-11-11 | 컨테이너 Ollama는 별도 `ollama` 프로필(`make dev-llm`) | 맥의 Docker에는 GPU가 없어서 네이티브 Ollama가 기본 경로다 |
| 2026-11-11 | `make migrate`는 api 컨테이너에서, `make test`는 호스트에서 실행 | 마이그레이션은 로컬과 EC2가 같은 경로로 돌고, 테스트는 dev 의존성이 있는 로컬 venv가 필요하다 |
| 2026-11-11 | 웹 패키지 매니저 npm | 별도 설치가 필요 없어 팀 진입장벽이 낮다 |
| 2026-11-11 | TypeScript 6.0.x 고정 | typescript-eslint 8.72가 TS 7을 지원하지 않는다(`<6.1.0`). 지원되면 올린다 |
| 2026-11-11 | create-vite 기본 oxlint 대신 ESLint + Prettier | 요구사항이다 |
| 2026-11-11 | ruff 설정은 `apps/api/pyproject.toml`, pre-commit은 `--config`로 공유 | 지금은 Python 코드가 api에만 있다. jobs/ml에 pyproject가 생기면 루트 `ruff.toml`로 승격한다 |
| 2026-11-11 | CI는 ruff → pytest → web 순서로 직렬 실행 | 요구사항의 순서를 따랐다. 시간이 문제가 되면 web job의 `needs`를 지워 병렬화한다 |
| 2026-11-11 | api 이미지가 약 900MB | pymupdf 2.x가 onnxruntime과 numpy를 끌어온다. PDF 파싱이 jobs/ingest로만 가면 api 의존성에서 빼는 것을 검토한다 |
