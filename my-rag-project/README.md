# ETF 길잡이 — 2주차 AI 에이전트 프로토타입 (RAG PoC)

1주차에 기획한 **ETF AI Agent**의 핵심인 '지식·FAQ 에이전트 + 컴플라이언스 가드'를
업로드한 PDF 문서만 근거로 답하는 RAG 프로토타입으로 만든 것이다(코멘토 2주차 실습 가이드 구조를 따른다).

- 사이드바에서 ETF 관련 PDF(투자설명서·안내서 등)를 올리면 **"문서 분석 완료"** 가 뜬다.
- 채팅창 질문에 문서 근거(파일·쪽 번호)를 붙여 답하고, 문서에 없으면 모른다고 답한다.
- 매수·매도 권유, 수익 보장 표현은 하지 않으며, 정보 답변에는 "투자 권유 아님" 고지를 붙인다.

## 디렉토리 구조

```
my-rag-project/
├── .env               # OpenAI API Key (보안 관리, git 제외) ← .env.example을 복사해 만든다
├── .env.example       # .env 형식 예시(키 없음)
├── requirements.txt   # 의존성 라이브러리 목록
├── rag_module.py      # 핵심 RAG 로직 (Backend)
├── app.py             # Streamlit 인터페이스 (Frontend)
└── sample_docs/
    └── sample_etf_guide.pdf   # 테스트용 샘플 ETF 안내서(가상 상품, 7쪽)
```

## 실행 방법

### Windows (PowerShell, 실습 가이드 기준)

```powershell
cd my-rag-project
python -m venv venv
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process   # 스크립트 실행 오류가 날 때만
.\venv\Scripts\activate                                             # 줄 앞에 (venv) 표시 확인
pip install -r requirements.txt
copy .env.example .env      # .env를 열어 OPENAI_API_KEY=발급받은키 로 수정
streamlit run app.py
```

### macOS / Linux

```bash
cd my-rag-project
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # OPENAI_API_KEY=발급받은키 로 수정
streamlit run app.py
```

Python 3.11 이상이 필요하다(고정한 streamlit·langchain-core·pymupdf 버전이 3.11부터 지원한다). 브라우저가 열리면(기본 http://localhost:8501) 아래 순서로 확인한다.

1. 사이드바에서 PDF를 업로드한다(없으면 `sample_docs/sample_etf_guide.pdf`).
2. "문서 분석 완료" 메시지가 뜨면 하단 채팅창에 질문한다.
3. 답변이 문서 내용을 근거로 하는지 '근거 문서'를 펼쳐 확인한다.

| 예시 질문 | 기대 동작 |
| --- | --- |
| 괴리율이 뭐야? → 그럼 괴리율이 크면 어떻게 돼? | 문서 근거 답변, 후속 질문은 앞 대화를 이어서 |
| 분배금은 언제 받아? | 근거 번호 `[n]`과 쪽 번호가 붙은 답변 |
| 총보수 얼마야? | 상품이 여러 개면 어느 상품인지 되묻기(재질의) |
| 지금 사면 무조건 오르겠지? | 판단 불가 안내 + 위험 정보 |
| 오늘 저녁 메뉴 추천해줘 | 범위 밖 안내 |

## RAG 파이프라인 8단계 ↔ 코드

| 단계 | 내용 | `rag_module.py` |
| --- | --- | --- |
| 1. 문서 로드 | PyMuPDF로 PDF 텍스트 추출(쪽 번호 보존, 빈 쪽 제외) | `load_pdf()`, `load_pdf_bytes()` |
| 2. 분할 | **400자** 청크, 50자 겹침(문단→줄→문장→단어 순) | `split_documents()` |
| 3. 임베딩 | `text-embedding-3-small` | `get_embeddings()` |
| 4. 벡터 DB 저장 | FAISS 인메모리 저장소 | `build_vectorstore()` |
| 5. 검색기 | 질문과 유사한 청크 k개(기본 4) | `get_retriever()` |
| 6. 프롬프트 | 역할·형식 지정, Few-shot, 재질의 지침 | `SYSTEM_PROMPT`, `build_prompt()` |
| 7. LLM | **GPT-4o**, temperature 0, 최대 600토큰 | `get_llm()` |
| 8. 출력 | 문자열 파싱 → 금지 표현 점검 → 고지 | `finalize_answer()` |

1~4단계는 `build_pipeline()`이 업로드 때 한 번, 5~8단계는 `RagPipeline.ask()`가 질문마다 실행한다.

## 프롬프트 엔지니어링 적용 (강의 자료 참고)

| 기법 | 적용 |
| --- | --- |
| 역할 지정 | "당신은 'ETF 길잡이'입니다. 자산운용사의 ETF 상담 AI 에이전트…" |
| 형식 지정 | `#역할` `#명령문` `#제약조건` `#입력문` `#출력형식` 단락으로 구성, 출력 형식을 대괄호로 지정 |
| 처리 단계 지정(Chain of Thought) | `[단계 1]~[단계 4]` 차근차근 생각하되 생각 과정은 출력하지 않게 |
| Few-shot · Q&A | 근거 답변 / 문서에 없음 / 권유·예측 요청 / 모호한 질문 4개 예시 |
| I Don't Know | 문서에 없으면 정해진 문장으로 "찾지 못했습니다" |
| 반응형 재질의 | 대상이 모호하면 한 문장으로 되묻기, 최근 3턴 대화를 기억해 답을 이어감 |
| 답변 길이 제한 | 5문장 이내 + 최대 600토큰 → 응답 속도·비용 절감 |
| 수준별 설명 | 입문·중급·숙련(1주차 기획의 수준별 FAQ) |

## 토큰 비용 관리 (chunk_size · k)

- 사이드바에서 `chunk_size`(200~1000)와 `k`(1~8)를 바꿔 가며 답변 품질과 비용을 비교한다.
  - **chunk_size**: 작으면 위치는 정확하지만 맥락이 잘리고, 크면 맥락은 넓지만 프롬프트 토큰이 는다(바꾸면 다시 분석).
  - **k**: 크면 근거를 많이 보지만 프롬프트 토큰과 응답 시간이 는다(바로 반영).
- 답변마다 응답 시간·토큰·비용(USD)이 표시되고, 사이드바에 누적 비용과
  **월 예상 비용(1회 평균 × 월 문의 수)** 이 나온다(강의 자료의 비용 산정 방식). 임베딩 비용은 제외.

## 보안

- API 키는 `.env`에만 둔다. `.env`와 `venv/`는 `.gitignore`로 커밋되지 않는다.
- 키가 없거나 예시 값 그대로면 화면에 안내만 띄우고 멈춘다.

## (선택) OpenAI 키 없이 로컬 모델로 시험

`.env`에 OpenAI 호환 서버 주소를 주면 같은 코드로 로컬 Ollama 모델을 쓸 수 있다(과제 기본값은 GPT-4o).

```dotenv
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=gemma3:12b
OPENAI_EMBEDDING_MODEL=snowflake-arctic-embed2
```

## 본 프로젝트와의 관계

레포 루트(`apps/`)는 같은 기획을 서비스 형태(FastAPI·LangGraph·pgvector·컴플라이언스 가드)로 만든 MVP이고,
이 폴더는 실습 가이드 구조(Streamlit + LangChain + FAISS + GPT-4o)를 따른 독립 실행 PoC다.
