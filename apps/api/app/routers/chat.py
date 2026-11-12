"""POST /chat (SSE). # P1-API-01"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.deps import ContainerDep, PrincipalDep
from app.services.chat import ChatRequest, stream_chat

router = APIRouter(tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # 프록시(nginx·cloudflared) 버퍼링 끄기
    "Connection": "keep-alive",
}


@router.post("/chat")
async def chat(body: ChatRequest, c: ContainerDep, principal: PrincipalDep) -> StreamingResponse:
    return StreamingResponse(
        stream_chat(c, principal, body), media_type="text/event-stream", headers=SSE_HEADERS
    )
