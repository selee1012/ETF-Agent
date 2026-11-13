"""요청 한 건의 LLM 호출을 기록하는 래퍼: 호출 수 메트릭, 폴백 사용 여부, 실제 답변 모델. # P1-OP-01·02

에이전트는 LLMResponse의 model·fallback_used를 버리고 본문만 쓴다. 그래프가 요청마다 이 래퍼로
LLM을 감싸 두면, 어느 단계에서 폴백이 쓰였는지와 답변을 쓴 모델이 트레이스에 남는다.
"""

from dataclasses import dataclass

from app.llm.base import ChatMessage, LLMClient, LLMError, LLMResponse
from app.observability.metrics import LLM_CALLS

# 사용자에게 보이는 답변을 쓰는 호출(트레이스의 model 컬럼은 이 호출의 모델을 적는다)
ANSWER_TASKS = frozenset({"answer", "general_answer"})


@dataclass(slots=True)
class LLMUsage:
    calls: int = 0
    fallback_used: bool = False
    answer_model: str | None = None


class TrackedLLM(LLMClient):
    def __init__(self, inner: LLMClient, usage: LLMUsage) -> None:
        self.inner = inner
        self.usage = usage
        self.model = inner.model

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
        self.usage.calls += 1
        try:
            resp = await self.inner.complete(
                messages,
                task=task,
                intent=intent,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        except LLMError:
            LLM_CALLS.labels(task, "error").inc()
            raise
        LLM_CALLS.labels(task, "fallback" if resp.fallback_used else "ok").inc()
        if resp.fallback_used:
            self.usage.fallback_used = True
        if task in ANSWER_TASKS:
            self.usage.answer_model = resp.model
        return resp
