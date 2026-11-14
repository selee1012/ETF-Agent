"""TRACER=langfuse 스텁(Phase 2). 구현 시 langfuse SDK는 이 파일에서만 import 한다."""

from app.observability.base import Tracer, TraceRecord

_MESSAGE = "TRACER=langfuse는 아직 구현되지 않았습니다(Phase 2). TRACER=pg를 사용하세요"


class LangfuseTracer(Tracer):
    def __init__(self) -> None:
        # 요청마다 record()가 실패하면 채팅은 되는데 트레이스만 조용히 빠진다. 기동할 때 막는다.
        raise NotImplementedError(_MESSAGE)

    async def record(self, trace: TraceRecord) -> None:
        raise NotImplementedError(_MESSAGE)
