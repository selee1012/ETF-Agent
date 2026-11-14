"""ETF 문서 RAG 모듈 (Backend) — 2주차 실습 8단계 파이프라인.

1주차 기획(ETF AI Agent)의 '지식·FAQ 에이전트 + 컴플라이언스 가드'를 PDF 문서 기반으로 축소한 프로토타입이다.

    1. 문서 로드(Document Load)  : load_pdf()          PyMuPDF로 PDF 텍스트 추출
    2. 분할(Text Split)          : split_documents()   400자 단위 청크
    3. 임베딩(Embedding)         : get_embeddings()    텍스트 → 벡터
    4. 벡터 DB 저장              : build_vectorstore() FAISS 저장소
    5. 검색기(Retriever)         : get_retriever()     질문과 유사한 청크 k개
    6. 프롬프트(Prompt)          : build_prompt()      역할·형식 지정·Few-shot·재질의 지침
    7. LLM                       : get_llm()           GPT-4o 답변 생성
    8. 출력(Output)              : finalize_answer()   문자열 파싱 + 준법 점검 + 고지

API 키는 .env의 OPENAI_API_KEY에서만 읽는다(코드에 두지 않는다).
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.callbacks import get_openai_callback
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 이 파일 옆의 .env를 읽는다(어느 폴더에서 실행해도 같은 설정).
load_dotenv(Path(__file__).with_name(".env"))

DEFAULT_CHUNK_SIZE = 400  # 실습 가이드: 400자 단위 청크
DEFAULT_CHUNK_OVERLAP = 50  # 문장이 청크 경계에서 잘려도 앞뒤 맥락이 남게
DEFAULT_K = 4
HISTORY_TURNS = 3  # 재질의·후속 질문을 위해 기억할 최근 대화(질문+답변) 수
LLM_MAX_TOKENS = 600  # 답변 길이 제한 → 생성 시간·비용 절감(강의: 속도는 답변 길이가 좌우)
LLM_TIMEOUT_SECONDS = 60

NOT_FOUND = "업로드한 문서에서 관련 내용을 찾지 못했습니다."
OUT_OF_SCOPE = "죄송합니다. 업로드한 ETF 문서와 관련된 질문에만 답할 수 있어요."
BLOCKED = (
    "죄송합니다. 이 질문에는 투자 판단으로 오해될 수 있어 답변을 드리기 어렵습니다. "
    "문서에 있는 상품 구조·위험·비용 정보는 안내해 드릴 수 있어요."
)
DISCLAIMER = "※ 업로드한 문서에 근거한 정보 제공이며 투자 권유가 아닙니다. ETF는 원금 손실이 발생할 수 있습니다."

LEVEL_GUIDE = {
    "입문": "투자를 처음 하는 사람 기준. 전문 용어는 쉬운 말로 풀고, 필요하면 생활 속 비유를 한 번 쓴다.",
    "중급": "ETF 기본 용어(NAV, 괴리율, 총보수 등)는 아는 사람 기준. 용어는 그대로 쓰고 구조와 차이를 설명한다.",
    "숙련": "전문 투자자 기준. 정의·수치·조건을 압축해서 전달한다.",
}

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------


def _base_url() -> str | None:
    return os.getenv("OPENAI_BASE_URL") or None  # 비우면 OpenAI 공식 API


def chat_model_name() -> str:
    return os.getenv("OPENAI_MODEL") or "gpt-4o"  # 실습 가이드: GPT-4o


def embedding_model_name() -> str:
    return os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"


def _api_key() -> str:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    # 로컬 OpenAI 호환 서버(Ollama 등)는 키를 검사하지 않지만 SDK가 빈 값을 거부한다.
    return key or ("local" if _base_url() else "")


def check_config() -> str | None:
    """설정 오류 메시지(없으면 None). 화면에서 먼저 확인해 친절하게 안내한다."""
    key = _api_key()
    if not key or key in {"your_api_key_here", "your-openai-api-key-here"}:
        return (
            "OPENAI_API_KEY가 없습니다. my-rag-project/.env 파일에 "
            "`OPENAI_API_KEY=발급받은키`를 넣고 다시 실행하세요."
        )
    return None


# ---------------------------------------------------------------------------
# 1. 문서 로드
# ---------------------------------------------------------------------------


def load_pdf(path: str | Path, *, display_name: str | None = None) -> list[Document]:
    """PDF → 페이지별 Document. 빈 페이지(스캔 이미지 등)는 버린다."""
    docs = PyMuPDFLoader(str(path)).load()
    name = display_name or Path(path).name
    out = []
    for d in docs:
        text = d.page_content.strip()
        if not text:
            continue
        page = int(d.metadata.get("page", 0)) + 1  # 사람이 읽는 1부터 시작하는 쪽 번호
        out.append(Document(page_content=text, metadata={"source": name, "page": page}))
    return out


def load_pdf_bytes(data: bytes, filename: str) -> list[Document]:
    """업로드된 PDF 바이트를 임시 파일로 저장해 읽는다(PyMuPDFLoader는 경로를 받는다)."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return load_pdf(tmp_path, display_name=filename)
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# 2. 분할
# ---------------------------------------------------------------------------


def split_documents(
    docs: list[Document],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Document]:
    """문단 → 줄 → 문장 → 단어 순으로 끊어 chunk_size 글자 이하 청크를 만든다."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=min(chunk_overlap, chunk_size // 4),
        separators=["\n\n", "\n", ". ", "다. ", " ", ""],
    )
    return splitter.split_documents(docs)


# ---------------------------------------------------------------------------
# 3. 임베딩
# ---------------------------------------------------------------------------


def get_embeddings() -> OpenAIEmbeddings:
    local = _base_url() is not None
    return OpenAIEmbeddings(
        model=embedding_model_name(),
        api_key=_api_key(),
        base_url=_base_url(),
        # OpenAI 공식 API는 tiktoken 토큰 길이 검사를 하고, 로컬 호환 서버는 원문 문자열을 보낸다.
        check_embedding_ctx_length=not local,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=2,
    )


# ---------------------------------------------------------------------------
# 4. 벡터 DB 저장
# ---------------------------------------------------------------------------


def build_vectorstore(chunks: list[Document], embeddings: OpenAIEmbeddings) -> FAISS:
    if not chunks:
        raise ValueError(
            "PDF에서 텍스트를 추출하지 못했습니다(스캔 이미지 PDF는 지원하지 않습니다)."
        )
    return FAISS.from_documents(chunks, embeddings)


# ---------------------------------------------------------------------------
# 5. 검색기
# ---------------------------------------------------------------------------


def get_retriever(vectorstore: FAISS, *, k: int = DEFAULT_K) -> VectorStoreRetriever:
    return vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": k})


# ---------------------------------------------------------------------------
# 6. 프롬프트 — 강의 기법: 역할 지정, 형식 지정(#명령문·#제약조건·#입력문·#출력형식),
#    처리 단계 지정(Chain of Thought), Q&A Few-shot(4개), 모르면 모른다, 반응형 재질의, 답변 길이 제한
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
#역할
당신은 'ETF 길잡이'입니다. 자산운용사의 ETF 상담 AI 에이전트로서, 사용자가 올린 문서(투자설명서·안내서 등)만 근거로 ETF 질문에 답합니다.
당신은 친절하고 정확하며, ETF·문서와 관련된 답변만 합니다.

#명령문
아래 #제약조건을 지키며 #입력문(참고 문서와 질문)을 읽고 #출력형식에 맞게 답하세요.
답하기 전에 다음 단계로 차근차근 생각하되, 생각 과정은 출력하지 마세요.
[단계 1] 질문이 무엇을 묻는지 파악합니다. 대상이 여러 개라 모호하면 되묻습니다.
[단계 2] 참고 문서에서 질문과 관련된 근거를 찾습니다.
[단계 3] 근거에 있는 내용만으로 설명 수준에 맞춰 답을 씁니다.
[단계 4] 사용한 근거 번호를 문장 끝에 [1]처럼 표시합니다.

#제약조건
- 참고 문서에 있는 내용만 사용합니다. 문서에 없으면 추측하지 말고 정확히 "{not_found}"라고만 답합니다.
- 보수·비율·날짜 같은 수치는 문서에 적힌 그대로 옮깁니다.
- 특정 상품의 매수·매도 권유, 수익 보장·단정 표현("무조건", "확실히 오른다"), 미래 가격 예측을 하지 않습니다.
  이런 요청에는 판단은 해 드릴 수 없다고 밝히고, 문서에 있는 구조·위험·비용 정보만 안내합니다.
- ETF·투자·업로드 문서와 무관한 질문에는 정확히 "{out_of_scope}"라고만 답합니다.
- 질문이 모호하면(예: 문서에 상품이 여러 개인데 어느 것인지 없음) 짐작하지 말고 한 문장으로 되묻습니다.
  되물을 때는 그 질문 한 문장만 출력하고 다른 설명은 붙이지 않습니다.
- 고지 문구는 시스템이 붙이므로 답변에 쓰지 않습니다.
- 개인정보(주민등록번호·계좌번호·전화번호)를 답변에 쓰지 않습니다.
- 한국어로, 핵심만 간결하게 5문장 이내로 답합니다.
- 설명 수준: {level} — {level_guide}

#출력형식
[핵심 답변 1~2문장 + 근거 번호]
[필요할 때만: 세부 내용 글머리표 2~4개]
(되물을 때는 질문 한 문장만 출력)

#예시
예시 1 — 문서에 근거가 있는 질문
참고 문서: [근거 1] (예시.pdf p.2) 괴리율은 ETF의 시장가격과 순자산가치(NAV)의 차이를 비율로 나타낸 것입니다.
Q: 괴리율이 뭐야?
A: 괴리율은 ETF가 거래소에서 거래되는 가격이 실제 순자산가치(NAV)와 얼마나 차이 나는지를 비율로 나타낸 값입니다. [1]

예시 2 — 문서에 없는 질문
Q: 이 ETF 운용역 연봉은 얼마야?
A: {not_found}

예시 3 — 권유·예측 요청
Q: 지금 사면 무조건 오르겠지?
A: 특정 시점의 매수나 수익 여부는 판단해 드릴 수 없어요. 대신 문서에 있는 상품 구조와 위험, 비용 정보를 안내해 드릴 수 있습니다.

예시 4 — 모호한 질문(반응형 재질의)
참고 문서: [근거 1] (예시.pdf p.7) 샘플 코스피200 총보수 연 0.045% … [근거 2] (예시.pdf p.7) 샘플 미국S&P500 총보수 연 0.07% …
Q: 총보수 얼마야?
A: 어떤 상품의 총보수를 알려 드릴까요? (예: 샘플 코스피200, 샘플 미국S&P500)

예시의 문서·수치는 형식 참고용이며, 실제 답변에는 이번 #입력문의 참고 문서만 사용합니다.
"""

USER_PROMPT = """\
#입력문
[참고 문서]
{context}

[질문]
{question}
"""


def build_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("history", optional=True),  # 최근 대화(후속 질문·재질의 응답)
            ("human", USER_PROMPT),
        ]
    ).partial(not_found=NOT_FOUND, out_of_scope=OUT_OF_SCOPE)


def format_context(docs: list[Document]) -> str:
    return "\n\n".join(
        f"[근거 {i}] ({d.metadata.get('source')} p.{d.metadata.get('page')})\n{d.page_content}"
        for i, d in enumerate(docs, 1)
    )


# ---------------------------------------------------------------------------
# 7. LLM
# ---------------------------------------------------------------------------


def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=chat_model_name(),
        api_key=_api_key(),
        base_url=_base_url(),
        temperature=0,  # 근거 기반 답변은 일관성이 우선
        max_tokens=LLM_MAX_TOKENS,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=2,
    )


# ---------------------------------------------------------------------------
# 8. 출력 — 문자열 파싱 후 준법 점검(1주차 기획의 컴플라이언스 가드 축소판)과 고지
# ---------------------------------------------------------------------------

# 부정형("원금이 보장되지 않습니다")은 걸리지 않도록 단정·권유 어미까지 본다.
BANNED_PATTERNS = [
    re.compile(r"무조건\s*(오릅|오를|올라|수익|이익|벌)"),
    re.compile(r"(원금|수익|이익)(을|이|가)?\s*보장(합니다|됩니다|해\s*드립니다|돼요|해요)"),
    re.compile(r"확실(히|하게)\s*(오릅|오를|올라|수익|이익|벌)"),
    re.compile(r"(지금|당장|꼭|반드시)\s*(사세요|매수하세요|파세요|매도하세요|투자하세요)"),
    re.compile(r"(손실|손해)\s*(이|가)?\s*(없습니다|절대\s*없)"),
]
_CITATION = re.compile(r"\[(\d{1,2})\]")


def check_compliance(answer: str) -> list[str]:
    """금지 표현에 걸린 패턴 목록(비어 있으면 통과)."""
    return [p.pattern for p in BANNED_PATTERNS if p.search(answer)]


def finalize_answer(answer: str) -> tuple[str, bool]:
    """(최종 답변, 차단 여부). 금지 표현이 있으면 안전 답변으로 바꾸고, 정보 답변에는 고지를 붙인다."""
    answer = answer.replace(DISCLAIMER, "").strip()  # 모델이 이전 답변을 따라 고지를 쓴 경우 제거
    if check_compliance(answer):
        return f"{BLOCKED}\n\n{DISCLAIMER}", True
    if not answer or answer in (NOT_FOUND, OUT_OF_SCOPE) or answer.endswith("?"):
        return answer or NOT_FOUND, False  # 안내·되묻기에는 고지를 붙이지 않는다
    return f"{answer}\n\n{DISCLAIMER}", False


@dataclass
class Source:
    index: int  # 프롬프트의 [근거 n] 번호
    file: str
    page: int
    text: str
    cited: bool  # 답변에 [n]으로 인용됐는지


@dataclass
class RagAnswer:
    answer: str
    sources: list[Source]
    blocked: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0  # OpenAI 공식 모델 단가 기준(로컬 모델은 0)
    elapsed_s: float = 0.0


@dataclass
class RagPipeline:
    """1~4단계로 만든 벡터 저장소를 들고 있다가, 질문마다 5~8단계를 실행한다."""

    vectorstore: FAISS
    files: list[str]
    n_pages: int
    n_chunks: int
    chunk_size: int
    k: int = DEFAULT_K
    _chain: object = field(default=None, repr=False)

    def ask(
        self, question: str, *, level: str = "입문", history: list[tuple[str, str]] | None = None
    ) -> RagAnswer:
        started = time.perf_counter()
        # 5. 검색기: 질문과 유사한 청크 k개
        docs = get_retriever(self.vectorstore, k=self.k).invoke(question)
        # 6~8. 프롬프트 → LLM → 문자열 (LCEL 체인)
        if self._chain is None:
            self._chain = build_prompt() | get_llm() | StrOutputParser()
        turns = []
        for q, a in (history or [])[-HISTORY_TURNS:]:
            # 고지는 화면용이라 대화 기록에서는 뺀다(모델이 따라 쓰지 않게).
            turns += [("human", q), ("ai", a.replace(DISCLAIMER, "").strip())]
        with get_openai_callback() as cb:  # 토큰·비용 집계(강의: API 비용 산정)
            raw = self._chain.invoke(
                {
                    "context": format_context(docs),
                    "question": question,
                    "history": turns,
                    "level": level,
                    "level_guide": LEVEL_GUIDE.get(level, LEVEL_GUIDE["입문"]),
                }
            )
        # 8. 출력: 준법 점검 + 고지
        answer, blocked = finalize_answer(raw)
        cited = {int(n) for n in _CITATION.findall(raw)}
        sources = [
            Source(
                i,
                d.metadata.get("source", ""),
                d.metadata.get("page", 0),
                d.page_content,
                i in cited,
            )
            for i, d in enumerate(docs, 1)
        ]
        return RagAnswer(
            answer=answer,
            sources=sources,
            blocked=blocked,
            prompt_tokens=cb.prompt_tokens,
            completion_tokens=cb.completion_tokens,
            cost_usd=cb.total_cost,
            elapsed_s=time.perf_counter() - started,
        )


def build_pipeline(
    files: list[tuple[str, bytes]],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    k: int = DEFAULT_K,
) -> RagPipeline:
    """업로드 파일들로 1~4단계(로드 → 분할 → 임베딩 → FAISS)를 실행한다."""
    pages: list[Document] = []
    for name, data in files:
        pages += load_pdf_bytes(data, name)  # 1. 문서 로드
    chunks = split_documents(pages, chunk_size=chunk_size)  # 2. 분할
    vectorstore = build_vectorstore(chunks, get_embeddings())  # 3. 임베딩 + 4. FAISS 저장
    return RagPipeline(
        vectorstore=vectorstore,
        files=[n for n, _ in files],
        n_pages=len(pages),
        n_chunks=len(chunks),
        chunk_size=chunk_size,
        k=k,
    )
