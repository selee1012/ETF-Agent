"""인증: AUTH_PROVIDER=local의 개발용 로그인. APP_ENV=local에서만 열린다. # P1-API-01"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import Principal
from app.deps import ContainerDep, PrincipalDep
from app.repositories import conversations as conv_repo
from app.settings import AppEnv, AuthProvider

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class DevLoginRequest(BaseModel):
    email: str = Field(pattern=_EMAIL, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 (OAuth 토큰 종류)
    user: UserOut


@router.post("/dev-login", response_model=TokenResponse)
async def dev_login(body: DevLoginRequest, c: ContainerDep) -> TokenResponse:
    s = c.settings
    if s.app_env is not AppEnv.LOCAL or s.auth_provider is not AuthProvider.LOCAL:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    email = body.email.strip().lower()
    role = "admin" if email in {e.lower() for e in s.admin_emails} else "user"
    async with c.maker() as session:
        user = await conv_repo.upsert_user(session, email, role)
    token = c.auth.issue(Principal(user_id=user.id, email=user.email, role=user.role))
    return TokenResponse(
        access_token=token, user=UserOut(id=str(user.id), email=user.email, role=user.role)
    )


@router.get("/me", response_model=UserOut)
async def me(principal: PrincipalDep) -> UserOut:
    return UserOut(id=str(principal.user_id), email=principal.email, role=principal.role)
