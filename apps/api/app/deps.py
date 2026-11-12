"""FastAPI 의존성: 컨테이너, 인증 주체, 운영자 권한."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.auth import AuthError, Principal
from app.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def optional_principal(request: Request, c: ContainerDep) -> Principal | None:
    token = _bearer(request)
    if not token:
        return None
    try:
        return await c.auth.authenticate(token)
    except AuthError:
        return None
    except NotImplementedError as e:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(e)) from e


async def current_principal(
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Principal:
    if principal is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "로그인이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


async def require_admin(
    request: Request,
    c: ContainerDep,
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Principal:
    """# P1-API-04 ADMIN_AUTH=local: role=admin, cf_access: Cloudflare Access(스텁)."""
    try:
        ok = await c.admin_verifier.verify(principal, request.headers)
    except NotImplementedError as e:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(e)) from e
    if not ok or principal is None:
        code = status.HTTP_401_UNAUTHORIZED if principal is None else status.HTTP_403_FORBIDDEN
        raise HTTPException(code, "운영자 권한이 필요합니다")
    return principal


PrincipalDep = Annotated[Principal, Depends(current_principal)]
AdminDep = Annotated[Principal, Depends(require_admin)]
