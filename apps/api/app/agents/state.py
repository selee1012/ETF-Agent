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
    # 일반 대화(GENERAL_CHAT_ENABLED, 로컬 전용). 분류기가 내지 않고 오케스트레이터가 바꿔 넣는다.
    GENERAL = "general"


# 전문 에이전트가 처리하는 의도(나머지는 템플릿)
AGENT_INTENTS = (Intent.ETF_INFO, Intent.FAQ, Intent.DISCLOSURE)
TEMPLATE_INTENTS = (Intent.HIGH_RISK, Intent.RECOMMENDATION, Intent.OUT_OF_SCOPE)


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
    agent: str
    content: str
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
    body: str
    disclaimer_ids: list[str]
    sources: list[Source]
    evidence: list[str]
    guard: GuardResult
    guard_history: Annotated[list[list[str]], operator.add]
    verdict: str
    answer: str
    model: str
    fallback_used: bool
