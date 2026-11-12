"""LLM_PROVIDER=fake: 테스트·키 없는 환경용 결정적 LLM/임베더.

- 기본 응답은 task 라벨로 고른다. 분류(classify)는 일부러 JSON이 아닌 값을 돌려
  오케스트레이터의 키워드 규칙 대체 경로를 탄다.
- 테스트는 script={task: [응답, ...]}로 응답을 순서대로 지정할 수 있다.
"""

import hashlib
import json
import math
import re
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from app.llm.base import ChatMessage, Embedder, LLMClient, LLMError, LLMResponse

Scripted = str | Exception | Callable[[list[ChatMessage]], str]

_EVIDENCE_RE = re.compile(r"\[근거 1\][^\n]*\n(.+?)(?:\n\[근거 \d+\]|\Z)", re.DOTALL)


def _first_sentences(text: str, n: int = 2) -> str:
    parts = re.split(r"(?<=[.!?다요])\s+", text.strip())
    return " ".join(p for p in parts[:n] if p).strip()


def _default(task: str, messages: list[ChatMessage]) -> str:
    last = messages[-1].content if messages else ""
    if task == "classify":
        return "분류 불가"  # JSON 파싱 실패 → 키워드 규칙 대체
    if task == "judge":
        return json.dumps(
            {"grounded": True, "is_solicitation": False, "issues": []}, ensure_ascii=False
        )
    if task == "faq_answer":
        m = _EVIDENCE_RE.search(last)
        if not m:
            return "제공된 자료로는 답하기 어렵습니다."
        body = "\n".join(ln for ln in m.group(1).splitlines() if not ln.startswith("#"))
        return f"{_first_sentences(body)} [1]"
    if task == "general_answer":
        return f"(fake) 일반 대화 응답: {last[:40]}"
    if task in ("etf_summary", "disclosure_summary"):
        return ""  # 요약 문장 없이 DB 표만 사용
    return "샘플 응답입니다."


class FakeLLM(LLMClient):
    def __init__(
        self, *, model: str = "fake-llm", script: dict[str, list[Scripted]] | None = None
    ) -> None:
        self.model = model
        self._script: dict[str, deque[Scripted]] = defaultdict(deque)
        for task, items in (script or {}).items():
            self._script[task].extend(items)
        self.calls: list[dict[str, Any]] = []

    def push(self, task: str, *items: Scripted) -> None:
        self._script[task].extend(items)

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
        self.calls.append({"task": task, "intent": intent, "json_mode": json_mode})
        queue = self._script.get(task)
        if queue:
            item = queue.popleft()
            if isinstance(item, Exception):
                raise item if isinstance(item, LLMError) else LLMError(str(item))
            text = item(messages) if callable(item) else item
        else:
            text = _default(task, messages)
        return LLMResponse(text=text, model=model or self.model)

    def count(self, task: str) -> int:
        return sum(1 for c in self.calls if c["task"] == task)


class FakeEmbedder(Embedder):
    """문자 bigram 해싱 임베딩: 같은 단어를 공유할수록 코사인 유사도가 높다."""

    def __init__(self, *, dim: int, model: str = "fake-embedding") -> None:
        self.dim = dim
        self.model = model

    def _vec(self, text: str) -> list[float]:
        compact = re.sub(r"\s+", "", text.lower())
        v = [0.0] * self.dim
        grams = [compact[i : i + 2] for i in range(max(len(compact) - 1, 1))]
        for g in grams:
            h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]
