"""TRACER=langfuse 스텁(Phase 2). 구현 시 langfuse SDK는 이 파일에서만 import 한다."""

from app.observability.base import Tracer, TraceRecord


class LangfuseTracer(Tracer):
    async def record(self, trace: TraceRecord) -> None:
        raise NotImplementedError("Langfuse 트레이서는 Phase 2에서 구현한다")
