"""LLM·임베딩 인터페이스. 에이전트·도구·RAG는 이 모듈만 import 한다."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    fallback_used: bool = False
    usage: dict[str, int] = field(default_factory=dict)


class LLMError(Exception):
    """LLM 호출 실패(타임아웃·연결·응답 오류). 원문 질의는 메시지에 넣지 않는다."""


class LLMUnavailableError(LLMError):
    """1순위가 실패했고 폴백도 없거나 허용되지 않음 → 안전 답변으로 대체한다."""


class LLMClient(ABC):
    model: str

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        task: str = "generate",
        intent: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """한 번에 전체 응답을 받는다. task는 메트릭·fake 응답 선택용 라벨이다."""


class Embedder(ABC):
    model: str
    dim: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """텍스트 목록 → L2 정규화된 벡터 목록(dim 차원)."""
