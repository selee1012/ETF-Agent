"""/metrics: Prometheus 형식. # P1-OP-02

API는 터널로 인터넷에 노출되므로 메트릭(트래픽·의도 분포·가드 차단율)을 누구나 읽지 못하게 한다.
- METRICS_TOKEN이 있으면 `Authorization: Bearer <토큰>`이 맞아야 한다(수집기의 bearer_token 설정).
- 없으면 APP_ENV=local에서만 열고, 그 밖의 환경에서는 404(끝점이 없는 것처럼).
"""

import secrets

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.deps import ContainerDep
from app.observability.metrics import render
from app.settings import AppEnv

router = APIRouter(tags=["ops"])


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request, c: ContainerDep) -> Response:
    token = c.settings.metrics_token
    if token is None:
        if c.settings.app_env is not AppEnv.LOCAL:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
    else:
        scheme, _, given = request.headers.get("authorization", "").partition(" ")
        ok = scheme.lower() == "bearer" and secrets.compare_digest(
            given.strip().encode(), token.get_secret_value().encode()
        )
        if not ok:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "메트릭 토큰이 필요합니다",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Response(render(), media_type="text/plain; version=0.0.4; charset=utf-8")
