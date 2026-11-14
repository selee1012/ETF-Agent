# ETF Agent

ETF 정보와 공시를 조회하고 문서 검색을 바탕으로 질문에 답하는 AI 에이전트 MVP입니다. FastAPI, LangGraph, PostgreSQL(pgvector), React로 구성된 모노레포입니다.

> 상품·시세·공시·문서는 개발용 샘플입니다. 실제 투자 판단에 사용하지 마세요.

## 주요 기능

- ETF 정보·공시 조회와 문서 기반 FAQ 답변, 출처·고지 표시
- 질문 의도에 따른 자료 수집과 답변 생성, 규칙·검증 모델 기반 가드 및 안전 답변
- 설명 수준 선택, 멀티턴 대화, 대화 삭제와 답변 피드백
- 운영 화면에서 트레이스·피드백 확인, 문서 업로드와 검색 확인
- 로컬 전용 일반 대화 모드(설명 수준은 적용되지 않음)와 OpenAI 호환 모델·fake 모델 선택

요청은 대체로 `질문 전처리 → 의도 분류 및 문서 검색 → 자료 수집 → 답변 합성 → 가드 → SSE 응답` 순서로 처리합니다. 고위험·추천 등 일부 질문은 고정 안내로 분기합니다. SSE는 가드를 통과한 답변을 나누어 전송합니다. 검증 모델은 근거 문서로 생성한 답변에만 호출합니다. DB 표만으로 만든 답변과 일반 대화 답변은 규칙 검사만 거치고, 캐시된 FAQ 답변은 필수 고지만 다시 확인하며, 고정 안내는 가드를 거치지 않습니다.

## 빠른 시작

Docker와 Compose v2.24 이상이 필요합니다. 테스트·린트에는 [uv](https://docs.astral.sh/uv/)와 Node.js 24가 추가로 필요합니다.

### API 키 없이 실행

```bash
./scripts/run-fake.sh
```

스크립트가 `.env`를 준비하고 DB·API·웹을 실행한 뒤 마이그레이션, 샘플 데이터 및 문서 적재를 수행합니다. fake 모델의 답변은 실제 모델의 품질을 나타내지 않습니다.

- 웹: <http://localhost:5173> — 이메일로 개발용 로그인
- API 문서: <http://localhost:8000/docs>
- 운영 화면: `admin@local.test`로 로그인 후 **운영** 탭 선택
- 종료: `./scripts/run-fake.sh down` (데이터 볼륨 유지)

### 실제 모델로 실행

```bash
cp .env.local.example .env.local
# .env.local의 LLM_API_KEY 주석을 해제하고 API 키 입력
./scripts/run-local.sh
```

기본 모델은 `gpt-5.4-nano`, 임베딩은 `text-embedding-3-small`(1024차원)입니다. 질문과 검색된 문서 일부가 모델 제공자에게 전송됩니다. `.env.local.example`은 로컬 일반 대화 모드를 켭니다. 끄려면 `.env.local`에서 `GENERAL_CHAT_ENABLED=false`로 설정하세요.

설정 변경 후 `./scripts/run-local.sh`를 다시 실행합니다. 로그는 `./scripts/run-local.sh logs`, 종료는 `./scripts/run-local.sh down`으로 확인하거나 실행할 수 있습니다. fake와 실제 임베딩을 전환할 때는 해당 실행 스크립트로 문서를 다시 적재하세요. 스크립트는 샘플 문서만 다시 임베딩하므로 운영 화면에서 올린 문서는 다시 업로드해야 합니다.

## 자주 쓰는 명령

```bash
make setup                       # 호스트 테스트·린트 의존성 설치
make test                        # API 테스트 (실행 중인 DB 필요)
make lint                        # Ruff, ESLint, Prettier, TypeScript 검사
make demo PROVIDER=fake          # 예제 질문 실행
make eval PROVIDER=fake          # 평가 리포트
make restart                     # API 재시작 (데이터 갱신 후 캐시 비우기)
make logs                        # API 로그
make down                        # 컨테이너 종료, 볼륨 유지
```

테스트는 `TEST_DATABASE_URL` 또는 `POSTGRES_*`로 지정한 서버에 별도의 `_test` DB를 만들며, **같은 이름의 기존 테스트 DB를 삭제하고 다시 생성합니다**. 실행 전에 대상 서버를 확인하세요.

직접 스택을 관리할 때는 `make up`, `make migrate`, `make seed`, `make ingest`, `make collect`를 사용합니다. `make ingest ARGS="data/samples/docs --force"`는 문서를 강제로 재적재합니다. 경로는 레포 루트 기준 상대 경로(컨테이너 안에서는 `/workspace` 아래)로 주며, 없는 경로면 오류로 끝납니다. `make help`에서 전체 명령을 볼 수 있습니다.

> **데이터를 갱신한 뒤에는 `make restart`로 API를 재시작하세요.** `make seed`, `make ingest`, `make collect`는 API와 다른 프로세스에서 실행되어 API의 메모리 캐시를 비우지 못합니다. 재시작하지 않으면 이전 FAQ 답변·시세는 최대 1시간, ETF 정보는 최대 1일 동안 그대로 나올 수 있습니다. 실행 스크립트(`run-fake.sh`, `run-local.sh`)로 처음 띄울 때와 운영 화면에서 문서를 업로드할 때는 필요 없습니다.

## 설정

실행 스크립트는 비어 있는 `.env` 설정을 채웁니다. `.env.local`이 있으면 같은 이름의 `.env` 값을 덮으며, `run-fake.sh`로 실행할 때도 읽힙니다(모델·임베딩 공급자만 fake로 바뀝니다). API 컨테이너에는 두 파일의 값이 들어가므로 API 설정은 파일에서 바꾸세요. API 설정 가운데 셸 환경변수로 덮을 수 있는 것은 `LLM_PROVIDER`, `EMBEDDING_PROVIDER`(또는 `make up PROVIDER=fake`)뿐입니다. compose와 Makefile이 직접 읽는 `POSTGRES_*`, `TEST_DATABASE_URL`, `VITE_*`는 셸 환경변수가 우선합니다. 설정의 전체 목록과 설명은 [`.env.example`](.env.example), 기본값과 검증 규칙은 [`settings.py`](apps/api/app/settings.py)를 참고하세요.

| 설정 | 용도 |
| --- | --- |
| `DATABASE_URL`, `POSTGRES_*` | PostgreSQL 연결 및 로컬 DB 설정 |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | 생성 모델 설정 (`fake` 또는 `openai_compat`) |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` | 임베딩 설정. DB 벡터 컬럼 차원은 마이그레이션할 때의 `EMBEDDING_DIM`(기본 1024)으로 정해지므로 이후에는 바꾸지 않음 |
| `GENERAL_CHAT_ENABLED` | 일반 대화 활성화. `APP_ENV=local`에서만 허용 |
| `ADMIN_EMAILS`, `LOCAL_JWT_SECRET` | 개발용 관리자 이메일과 JWT 서명 키. 관리자 역할은 로그인할 때 토큰에 담기므로 목록 변경은 다시 로그인한 뒤 반영 |
| `METRICS_TOKEN` | `/metrics` 수집용 Bearer 토큰. 비우면 `APP_ENV=local`에서만 열림 |
| `DATA_GO_KR_API_KEY`, `DART_API_KEY` | 외부 데이터 수집 키 |

## API

인증이 필요한 API는 개발용 로그인으로 받은 JWT를 사용합니다. 상세 요청·응답은 실행 후 `/docs`에서 확인할 수 있습니다.

| 경로 | 기능 |
| --- | --- |
| `GET /health`, `GET /metrics` | 상태 확인과 Prometheus 메트릭(`METRICS_TOKEN` 설정 시 Bearer 토큰 필요) |
| `POST /auth/dev-login`, `GET/PATCH /auth/me` | 로컬 로그인과 설명 수준 설정 |
| `POST /chat` | 채팅 SSE (`status` → `token` → `sources` → `done`). 대화 저장이나 답변 작업이 실패하면 `done` 없이 `error`로 끝남 |
| `GET/DELETE /history`, `GET/DELETE /history/{id}` | 대화 조회·삭제 |
| `POST /feedback` | 좋아요·싫어요·정정 피드백 |
| `/admin/traces`, `/admin/feedback`, `/admin/documents`, `/admin/search` | 관리자 전용 운영 API |

대화를 삭제하면 메시지도 삭제되지만 피드백과 트레이스는 남습니다. 대화 내용은 저장 전 개인정보 패턴을 마스킹하며, 트레이스에는 질문 원문을 저장하지 않도록 구성되어 있습니다.

## 현재 범위와 배포

로컬 실행이 중심인 MVP입니다. 배포 구성은 Azure와 Supabase를 계획하고 있으며, 실제 로그인 수단 및 Supabase/Entra 인증, Supabase·Azure Blob 저장소, Cloudflare Access, Langfuse 어댑터는 아직 구현이 필요합니다. 구현 전인 인증·저장소를 고르면 해당 요청이 501로 응답하고, Langfuse 트레이서를 고르면 API가 기동하지 않습니다. 자세한 구성은 [Azure 안내](infra/azure/README.md)를 참고하세요.

가드의 검증 모델을 호출하지 못하거나 판정 결과를 두 번 연속 해석하지 못하면 답변을 내보내지 않고 안전 답변으로 대체합니다. 캐시는 프로세스별 메모리에 있으므로 별도 프로세스의 데이터 적재나 다른 API 인스턴스에 캐시 삭제가 전파되지 않습니다. 로컬에서는 `make restart`로 해결하고, API 인스턴스를 여러 개 띄우는 배포에서는 공유 캐시(Redis 등)가 필요합니다.

## 디렉터리

| 경로 | 내용 |
| --- | --- |
| [`apps/api/`](apps/api/) | FastAPI, 에이전트, RAG, 저장소, 마이그레이션 및 테스트 |
| [`apps/web/`](apps/web/) | React 채팅·운영 화면 |
| [`jobs/`](jobs/) | 샘플 시드, 문서 적재, 외부 데이터 수집 |
| [`ml/`](ml/) | 오프라인 평가(`make eval`) |
| [`scripts/`](scripts/) | 실행 스크립트와 예제 질문 실행 |
| [`data/`](data/) | 샘플 데이터와 평가 데이터셋 |
| [`prompts/`](prompts/) | 시스템 프롬프트, 가드 규칙과 답변 템플릿 |
| [`infra/`](infra/) | 로컬 Docker 및 배포 설정 예시 |
| [`my-rag-project/`](my-rag-project/README.md) | 별도 실행하는 Streamlit·LangChain RAG 실습 |
