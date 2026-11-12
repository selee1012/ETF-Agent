"""/metrics: Prometheus 형식. # P1-OP-02"""

from fastapi import APIRouter, Response

from app.observability.metrics import render

router = APIRouter(tags=["ops"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(render(), media_type="text/plain; version=0.0.4; charset=utf-8")
