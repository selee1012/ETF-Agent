# 고도화 버전: AWS에서 모델 쓰기

로컬은 Ollama(또는 fake)로 개발하고, 고도화·배포 버전은 AWS에서 모델을 쓴다.
코드 변경 없이 **환경변수만** 바꿔 아래 세 방식 중 하나를 고른다(공통 규칙 3).

| 방식 | 생성 모델 | 임베딩 | 질의가 나가는 곳 | 운영 부담 |
| --- | --- | --- | --- | --- |
| **A. Bedrock** (기본 권장) | Bedrock 관리형 모델 | Titan Embed v2 | AWS Bedrock(같은 리전) | 낮음 |
| **B. 자체 호스팅 sLLM** | EC2/ECS GPU + vLLM (Mi:dm 등) | Titan 또는 vLLM 임베딩 | VPC 안의 우리 서버 | 높음(GPU 상시) |
| **C. B + Bedrock 폴백** | vLLM, 장애 시 Bedrock | 위와 같음 | 평소 VPC, 장애 시 Bedrock | 높음 |

어떤 방식이든 질의는 저장 전 `privacy.mask_pii()`를 거치고, 답변은 컴플라이언스 가드를 통과해야 나간다.
외부 API 사용이 사내 보안 정책상 불가하면 B를 쓴다.

## A. Bedrock

설정 예시: [`bedrock.env.example`](bedrock.env.example)

```dotenv
LLM_PROVIDER=bedrock
BEDROCK_REGION=ap-northeast-2
LLM_MODEL=<생성 모델 ID 또는 추론 프로필 ID>
JUDGE_MODEL=<검증 모델 ID — 비우면 LLM_MODEL>
EMBEDDING_PROVIDER=bedrock
EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
EMBEDDING_DIM=1024
```

- 생성은 **Converse API**를 쓰므로 Converse를 지원하는 모델이면 ID만 바꿔 쓸 수 있다.
  예: Amazon Nova(`amazon.nova-lite-v1:0`), Anthropic Claude, Meta Llama, Mistral.
  서울 리전에서 바로 쓸 수 없는 모델은 교차 리전 **추론 프로필 ID**(`apac.` 접두사 등)를 `LLM_MODEL`에 넣는다.
  리전별 지원 모델은 콘솔 Bedrock → Model catalog에서 확인한다.
- 임베딩은 `amazon.titan-embed-text-v2:0`(256/512/1024차원)과 `cohere.embed-multilingual-v3`(1024차원)를 지원한다.
  DB 컬럼이 1024차원이므로 `EMBEDDING_DIM=1024`를 유지하면 마이그레이션이 필요 없다.
  로컬(Ollama)에서 쓰던 임베딩과 모델이 다르면 `make ingest`가 바뀐 모델을 감지해 다시 임베딩한다.
- 자격 증명은 boto3 기본 체인을 쓴다: ECS 태스크 역할/EC2 인스턴스 프로필 → `AWS_*` 환경변수 → `~/.aws`.
  **액세스 키를 .env에 넣지 않는다.** 로컬에서 시험할 때만 `BEDROCK_PROFILE=<~/.aws 프로필>`을 쓴다.
- IAM 최소 권한(실행 역할):

  ```json
  {
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel"],
    "Resource": [
      "arn:aws:bedrock:ap-northeast-2::foundation-model/<생성 모델 ID>",
      "arn:aws:bedrock:ap-northeast-2::foundation-model/amazon.titan-embed-text-v2:0"
    ]
  }
  ```

  추론 프로필을 쓰면 프로필 ARN(`arn:aws:bedrock:<리전>:<계정>:inference-profile/<ID>`)과
  프로필이 라우팅하는 리전들의 foundation-model ARN도 함께 허용해야 한다.
- 타임아웃·재시도: `LLM_TIMEOUT_SECONDS`(읽기 타임아웃), 연결 5초, 표준 재시도 2회.
  실패하면 `LLMError` → 그래프가 안전 답변(`llm_unavailable`)을 낸다.

## B. 자체 호스팅 sLLM (vLLM)

설정 예시: [`vllm.env.example`](vllm.env.example)

vLLM은 OpenAI 호환 API를 제공하므로 로컬 Ollama와 **같은 어댑터(openai_compat)** 를 쓴다.
Hugging Face 모델을 그대로 올릴 수 있어 Mi:dm처럼 Ollama 공식 등록이 없는 모델도 쓸 수 있다.

```bash
# GPU 인스턴스(예: g6.xlarge, L4 24GB)에서
vllm serve K-intelligence/Midm-2.0-Mini-Instruct \
  --served-model-name midm-2.0-mini --max-model-len 8192 --port 8000
```

```dotenv
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://<vLLM 프라이빗 IP 또는 내부 DNS>:8000/v1
LLM_MODEL=midm-2.0-mini
# 임베딩은 Bedrock Titan을 섞어 쓸 수 있다(공급자를 따로 고른다)
EMBEDDING_PROVIDER=bedrock
EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
EMBEDDING_DIM=1024
```

- vLLM 서버는 프라이빗 서브넷에 두고 보안 그룹으로 API 서버에서만 접근하게 한다.
- 모델 라이선스를 확인한다(Mi:dm 2.0 MIT, EXAONE은 비상업 라이선스라 상용 불가).

## C. 자체 호스팅 + Bedrock 폴백

B 설정에 다음을 더한다. `FALLBACK_ALLOWED_INTENTS`에 든 의도만 Bedrock으로 넘어간다.

```dotenv
FALLBACK_PROVIDER=bedrock
BEDROCK_MODEL_ID=<폴백 모델 ID>
FALLBACK_ALLOWED_INTENTS=faq
```

## 배포 시 함께 바꿀 값

- `APP_ENV=prod` — 이때 `LOCAL_JWT_SECRET`이 없으면 기동하지 않는다.
- `DATABASE_URL` — RDS/Aurora PostgreSQL(pgvector·pg_trgm 확장 필요).
- 인증·저장소·트레이서 어댑터(`AUTH_PROVIDER`, `STORAGE_PROVIDER`, `TRACER`)는 루트 README의 확장 지점 참고.
