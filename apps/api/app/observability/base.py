"""트레이서 인터페이스. TraceRecord에는 질의 원문 필드가 없다(공통 규칙 4). # P1-OP-01"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class TraceRecord:
    request_id: str
    user_id: uuid.UUID | None
    intent: str | None
    agents: list[str] = field(default_factory=list)
    retrieved_doc_ids: list[str] = field(default_factory=list)
    guard_verdict: str | None = None
    guard_reasons: list[str] = field(default_factory=list)
    latency_ms: int | None = None
    model: str | None = None
    fallback_used: bool = False


class Tracer(ABC):
    @abstractmethod
    async def record(self, trace: TraceRecord) -> None:
        """요청 1건의 트레이스를 남긴다. 실패해도 응답은 막지 않는다(호출 측이 예외 처리)."""
