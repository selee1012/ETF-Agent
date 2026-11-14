# 고도화 버전: Azure 구성

로컬은 Docker(Postgres·OpenAI API 또는 fake)로 개발하고, 고도화·배포 버전은 **Azure**에 둔다.
DB만 비용을 줄이려고 **Supabase 서울 리전**을 쓴다(아래 DB 절).
코드 변경 없이 **환경변수만** 바꿔 옮기는 것이 원칙이다. 아직 스텁인 어댑터는 아래 표에 표시했다.

## AWS → Azure 대응표

| 역할 | 이전 계획(AWS) | Azure | 이 레포에서 바꿀 것 | 상태 |
| --- | --- | --- | --- | --- |
| 생성 모델(관리형) | Bedrock | **Azure OpenAI**(Microsoft Foundry) | `LLM_PROVIDER=openai_compat`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`=배포 이름 | 동작(로컬에서 실측) |
| 임베딩 | Bedrock Titan v2 | Azure OpenAI `text-embedding-3-small`(`dimensions=1024`) | `EMBEDDING_MODEL`=배포 이름, `EMBEDDING_REQUEST_DIMENSIONS=true` | 동작 |
| 자체 호스팅 sLLM | EC2/ECS GPU + vLLM | Azure GPU VM(NC 계열) 또는 AKS GPU 노드 + vLLM | `LLM_BASE_URL`=VNet 내부 주소 | 동작(어댑터 공통) |
| LLM 폴백 | Bedrock | Azure OpenAI | `FALLBACK_PROVIDER=openai_compat`, `FALLBACK_BASE_URL`, `FALLBACK_API_KEY`, `FALLBACK_MODEL` | 동작(vLLM을 1순위로 쓸 때만 의미 있음) |
| DB | RDS/Aurora PostgreSQL | **Supabase 서울 리전 유지**(비용). 대안: Azure Database for PostgreSQL Flexible Server | `DATABASE_URL` | 코드 변경 없음 |
| 인증 | Cognito | **자체 발급 JWT 유지**(기본) 또는 Microsoft Entra External ID | `AUTH_PROVIDER=local` 또는 `entra` | local은 로그인 수단 보강 필요, entra는 스텁 |
| 파일 저장 | S3 | **Azure Blob Storage** | `STORAGE_PROVIDER=azure_blob` | 스텁(`app/storage/azure_blob.py`) |
| API 실행 | ECS Fargate | Azure Container Apps | 컨테이너 환경변수 | — |
| 배치(`jobs/`) | EventBridge + ECS 태스크 | Container Apps Jobs(예약 실행) | — | — |
| 웹(정적) | S3 + CloudFront | Azure Static Web Apps | `VITE_API_BASE_URL` | — |
| 이미지 저장소 | ECR | Azure Container Registry | — | — |
| 비밀값 | Secrets Manager | Key Vault(Container Apps 비밀 참조) | — | — |
| 서비스 간 권한 | IAM 역할 | 관리 ID(Managed Identity) + RBAC | — | — |
| 네트워크 | VPC·보안 그룹 | VNet·NSG·Private Endpoint | — | — |
| 로그·지표 | CloudWatch | Azure Monitor(Log Analytics·Application Insights) | — | — |

어떤 방식이든 질의는 저장 전 `privacy.mask_pii()`를 거치고, 답변은 컴플라이언스 가드를 통과해야 나간다.

## 모델

### A. Azure OpenAI (기본 권장)

설정 예시: [`azure-openai.env.example`](azure-openai.env.example)

Azure OpenAI의 v1 엔드포인트는 OpenAI API와 형식이 같아 로컬과 **같은 어댑터(openai_compat)** 를 쓴다.
`LLM_MODEL`·`EMBEDDING_MODEL`에는 모델 이름이 아니라 **배포 이름**을 넣는다.

```dotenv
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://<리소스 이름>.openai.azure.com/openai/v1/
LLM_MODEL=<생성 모델 배포 이름>
EMBEDDING_MODEL=<임베딩 배포 이름>
EMBEDDING_DIM=1024
EMBEDDING_REQUEST_DIMENSIONS=true
```

- 로컬과 같은 임베딩 모델(`text-embedding-3-small`, 1024차원)을 쓰면 다시 임베딩할 필요가 없다.
- `LLM_API_KEY`는 Key Vault에 두고 Container Apps 비밀 참조로 주입한다. `.env`에 넣지 않는다.
  키 없이 관리 ID 토큰으로 호출하는 방식은 아직 어댑터에 없다(필요하면 `app/llm/openai_compat.py`에 추가).
- 모델·배포 유형(GlobalStandard 등)별 할당량은 구독마다 다르다. 무료 체험 구독은 koreacentral에서
  `gpt-5-mini`·`text-embedding-3-small`만 할당량이 있었다(2026-11 기준).
- 타임아웃·재시도는 로컬과 같다(`LLM_TIMEOUT_SECONDS`). 실패하면 `LLMError` → 안전 답변(`llm_unavailable`).

### B. 자체 호스팅 sLLM (vLLM)

설정 예시: [`vllm.env.example`](vllm.env.example)

외부 API 사용이 보안 정책상 불가할 때 쓴다. vLLM도 OpenAI 호환 API라 같은 어댑터를 쓴다
(`OPENAI_MAX_TOKENS_PARAM=max_tokens`, `OPENAI_OMIT_TEMPERATURE=false`, `OPENAI_REASONING_EFFORT=off`).

```bash
# GPU VM(예: NC 계열 T4 16GB)에서
vllm serve K-intelligence/Midm-2.0-Mini-Instruct \
  --served-model-name midm-2.0-mini --max-model-len 8192 --port 8000
```

- vLLM 서버는 VNet의 프라이빗 서브넷에 두고 NSG로 API 서버에서만 접근하게 한다.
- GPU VM은 구독 할당량 신청이 필요하다(무료 체험 구독은 GPU 할당량이 없다).
- 생성과 임베딩은 엔드포인트를 따로 둘 수 있지만(`EMBEDDING_BASE_URL`) **API 키는 하나(`LLM_API_KEY`)를 같이 쓴다.**
  vLLM 생성 + Azure OpenAI 임베딩을 섞으려면 vLLM을 `--api-key`로 같은 값에 맞추거나, 임베딩도 vLLM에서 띄운다.
- 모델 라이선스를 확인한다(Mi:dm 2.0 MIT, EXAONE은 비상업 라이선스라 상용 불가).

### C. 자체 호스팅 + Azure OpenAI 폴백

B 설정에 다음을 더한다. vLLM 호출이 실패하면 `FALLBACK_ALLOWED_INTENTS`에 든 의도만 Azure OpenAI로 다시 호출한다.

```dotenv
FALLBACK_PROVIDER=openai_compat
FALLBACK_BASE_URL=https://<리소스 이름>.openai.azure.com/openai/v1/
FALLBACK_MODEL=<폴백 모델 배포 이름>
FALLBACK_ALLOWED_INTENTS=faq
```

- `FALLBACK_API_KEY`는 Key Vault 비밀 참조로 주입한다. URL이나 모델이 비어 있으면 기동하지 않는다.
- 폴백은 gpt-5 계열 형식(`max_completion_tokens`, 온도 생략)으로 부른다. 생각 분량은 `FALLBACK_REASONING_EFFORT`(기본 `minimal`).

## DB — Supabase 서울 리전 (비용 우선)

- 프로젝트를 만들 때 리전을 **Northeast Asia (Seoul)**, `ap-northeast-2`로 고른다. Azure koreacentral도 서울이라 API ↔ DB 지연이 작다.
- `DATABASE_URL`은 **Session pooler(5432)** 주소를 `postgresql+asyncpg://` 스킴으로 넣는다
  (Transaction pooler는 asyncpg prepared statement와 충돌한다). pgvector·pg_trgm은 마이그레이션이 `extensions` 스키마에 만든다(이 스키마가 없는 로컬·Azure에서는 기본 스키마).
- 무료 플랜은 DB 500MB이고 **1주일 동안 사용이 없으면 일시 중지**된다(데이터는 남고 수동 복구). 데모·개발은 무료로,
  상시 운영은 Pro로 올린다. 요금·한도는 바뀔 수 있으니 supabase.com/pricing에서 확인한다.
- Supabase는 Azure 밖(AWS 서울)에 있어 연결이 공용 인터넷(TLS)을 지난다. VNet 안에만 DB를 둬야 하는 보안 요건이 생기면 아래 대안으로 옮긴다.

### 대안: Azure Database for PostgreSQL Flexible Server

`DATABASE_URL`만 바꾸면 된다. 인스턴스가 상시 과금되므로 사설망(Private Endpoint)·규모가 필요해질 때 쓴다.

- 서버 매개변수 `azure.extensions`에 `VECTOR`, `PG_TRGM`을 허용 목록으로 넣어야 마이그레이션의 `CREATE EXTENSION`이 통과한다.
- `DATABASE_URL=postgresql+asyncpg://<사용자>:<비밀번호>@<서버>.postgres.database.azure.com:5432/<DB>?ssl=require`
- 로컬 이미지와 같은 메이저 버전(PostgreSQL 17)을 고른다.

## 인증 — JWT는 그대로

API는 어느 방식이든 **Bearer JWT를 검증**한다(`app/auth/base.py`의 `AuthBackend`). 달라지는 것은 "누가 로그인시키고 토큰을 발급하는가"뿐이다.

| 방식 | 발급 | 설정 | 더 만들 것 |
| --- | --- | --- | --- |
| 자체 발급 JWT(기본) | API 서버 | `AUTH_PROVIDER=local`, `LOCAL_JWT_SECRET`(Key Vault) | 실제 로그인 수단. 지금 `dev-login`은 이메일만 받아 토큰을 주며 `APP_ENV=local`에서만 열린다 |
| Supabase Auth | Supabase | `AUTH_PROVIDER=supabase`, `SUPABASE_URL` | `app/auth/supabase_jwt.py`(JWKS 검증), web `src/lib/auth.ts`. DB를 Supabase에 두면 추가 비용 없이 쓸 수 있다 |
| Entra External ID | Azure | `AUTH_PROVIDER=entra`, `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` | `app/auth/entra_jwt.py`(JWKS 검증), web 로그인 연동 |

자체 발급으로 갈 때 배포 전에 필요한 것: 비밀번호(해시 저장) 또는 소셜 로그인, 토큰 만료·재발급(지금은 12시간 단일 토큰),
로그인 시도 제한. 가입·비밀번호 재설정·소셜 로그인을 직접 만들고 싶지 않을 때 Supabase Auth나 Entra External ID로 넘어간다.

## 파일 저장 — Blob에 원본, DB에는 주소만

- 원본 파일(PDF 등)은 Blob 컨테이너에 두고, Postgres `documents.source_uri`에 주소(`azure_blob://uploads/…`)만 남긴다.
  운영 화면 업로드의 지금 로컬 구조(`local://uploads/…`)와 같아서 어댑터만 구현하면 된다(`make ingest`로 넣은 문서는 `file://…`이고 저장소를 거치지 않는다).
- 질문에 답할 때 읽는 것은 원본이 아니라 DB의 `chunks`(본문 조각·임베딩)다. 자주 조회되는 내용은 이미 DB에 있으므로
  원본을 DB에 중복 저장할 필요가 없다. 원본은 다시 ingest하거나 내려받을 때만 Blob에서 읽으면 되는데, 이 두 기능은 아직 없다(지금 저장소를 읽는 곳은 업로드 실패 시 되돌리기뿐이다).
- Blob에만 두고 DB 기록을 없애는 방식은 쓰지 않는다. 목록·검색은 DB의 문서·청크를 읽고, 재-ingest는 `source_uri`로 같은 문서를 찾아 갱신한다.
- 컨테이너는 비공개로 두고, API는 관리 ID(Storage Blob Data Contributor)로 접근한다. 사용자에게 원본을 내려줄 때는 만료 시간이 짧은 SAS URL을 쓴다.

## 배포 시 함께 바꿀 값

- `APP_ENV=prod` — `AUTH_PROVIDER=local`이면 `LOCAL_JWT_SECRET`이 없을 때 기동하지 않는다.
- `CORS_ORIGINS` — Static Web Apps 주소.
- `TRACER` — `pg`만 동작한다. `langfuse`는 스텁이라 고르면 API가 기동하지 않는다.
- `ADMIN_AUTH` — `local`(JWT의 `role=admin`)만 동작한다. `cf_access`(Cloudflare Access)는 스텁이라 운영 API가 501로 응답한다.
