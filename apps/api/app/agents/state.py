"""그래프 상태와 공용 자료형."""

import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.base import Embedder, LLMClient
from app.settings import Settings


class Intent(StrEnum):
    ETF_INFO = "etf_info"
    FAQ = "faq"
    DISCLOSURE = "disclosure"
    HIGH_RISK = "high_risk"
    RECOMMENDATION = "recommendation"
    OUT_OF_SCOPE = "out_of_scope"
    # 해킹·불법 행위 방법 요청, 지침 무력화(프롬프트 인젝션) 시도: 생성 없이 즉시 차단 # P1-AG-06
    BLOCKED = "blocked"
    # 일반 대화(GENERAL_CHAT_ENABLED, 로컬 전용). 분류기가 내지 않고 오케스트레이터가 바꿔 넣는다.
    GENERAL = "general"


# 전문 에이전트가 처리하는 의도(나머지는 템플릿)
AGENT_INTENTS = (Intent.ETF_INFO, Intent.FAQ, Intent.DISCLOSURE)
TEMPLATE_INTENTS = (Intent.BLOCKED, Intent.HIGH_RISK, Intent.RECOMMENDATION, Intent.OUT_OF_SCOPE)


class Level(StrEnum):
    BEGINNER = "beginner"  # 입문
    INTERMEDIATE = "intermediate"  # 중급
    EXPERT = "expert"  # 숙련


class Verdict(StrEnum):
    PASS = "pass"  # noqa: S105 (판정 라벨)
    PASS_AFTER_RETRY = "pass_after_retry"  # noqa: S105
    BLOCKED = "blocked"  # 재생성 후에도 실패 → 안전 답변
    TEMPLATE = "template"  # 고위험·추천·범위 밖 고정 답변
    LLM_UNAVAILABLE = "llm_unavailable"  # LLM 실패, 폴백 없음 → 안전 답변


@dataclass(slots=True)
class EtfEntity:
    ticker: str
    name: str
    matched: str  # 질문에서 매칭된 표현(정규화)
    score: float
    method: str  # exact | ticker | fuzzy | context


@dataclass(slots=True)
class Source:
    title: str
    location: str | None = None
    url: str | None = None
    kind: str = "document"  # document | disclosure | etf_data
    doc_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "location": self.location,
            "url": self.url,
            "kind": self.kind,
            "doc_id": self.doc_id,
        }


@dataclass(slots=True)
class AgentResult:
    """수집 에이전트 결과. LLM은 부르지 않고, 답변 합성(compose)이 모아서 한 번에 쓴다. # P1-AG-02"""

    agent: str
    content: str  # 화면에 그대로 붙는 결정적 블록(DB 표·공시 목록·안내 문구). FAQ는 비움(캐시 적중 시 답변)
    sources: list[Source] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)  # 가드 근거 대조용 텍스트
    retrieved_ids: list[str] = field(default_factory=list)
    generated: bool = False  # LLM 생성 문장이 포함됐는지(검증 모델 대상)
    grounded: bool = (
        True  # False: 근거 없이 모델 일반 지식으로 답함(일반 대화) → 수치·근거 검증 생략
    )
    ok: bool = True
    error: str | None = None
    cache_key: str | None = None  # 가드 통과 시 캐시에 저장할 키(FAQ)
    cached: bool = False
    found: bool = True  # 답에 쓸 자료를 찾았는지(False면 content는 안내 문구)
    context: str = ""  # LLM 프롬프트에 넣을 자료 블록([ETF 데이터]·[공시]·[근거 N])


@dataclass(slots=True)
class GuardResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    judge: dict[str, Any] | None = None


Emit = Callable[[str, str], Awaitable[None]]


async def _noop_emit(stage: str, message: str) -> None:
    return None


@dataclass(slots=True)
class AgentDeps:
    settings: Settings
    llm: LLMClient
    embedder: Embedder
    maker: async_sessionmaker[AsyncSession]
    emit: Emit = _noop_emit


def merge_results(left: dict[str, AgentResult], right: dict[str, AgentResult]) -> dict:
    return {**(left or {}), **(right or {})}


class GraphState(TypedDict, total=False):
    request_id: str
    query: str  # 원문: 메모리 안에서만 쓰고 저장·로그·트레이스에 남기지 않는다
    normalized: str
    level: str
    history: list[dict[str, Any]]  # [{"role","content"(마스킹됨),"meta"}]
    context_tickers: list[str]  # 직전 턴 엔티티(멀티턴)
    entities: list[EtfEntity]
    intents: list[str]
    intent_source: str  # llm | rules
    results: Annotated[dict[str, AgentResult], merge_results]
    agents_called: Annotated[list[str], operator.add]
    attempt: int
    retry_feedback: list[str]
    prefetched_chunks: list[Any] | None  # 의도 분류와 동시에 미리 검색한 문서 청크(RetrievedChunk)
    body: str
    disclaimer_ids: list[str]
    sources: list[Source]
    evidence: list[str]
    generated: bool  # 답변에 LLM 생성 문장이 있는지(검증 모델 대상)
    grounded: bool  # False: 근거 없이 모델 일반 지식으로 답함
    cached: bool  # FAQ 캐시 적중
    cache_key: str | None  # 가드 통과 시 FAQ 캐시에 저장할 키
    guard: GuardResult
    guard_history: Annotated[list[list[str]], operator.add]
    verdict: str
    answer: str
    model: str
    fallback_used: bool
