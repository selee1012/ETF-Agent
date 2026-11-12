"""인증: AUTH_PROVIDER=local의 개발용 로그인(APP_ENV=local에서만), 내 프로필 조회·수정. # P1-API-01

프로필의 level(설명 수준)은 처음 로그인할 때 고르고(NULL이면 웹이 온보딩을 띄운다),
채팅 요청에 level이 없으면 이 값으로 답한다.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.agents.state import Level
from app.auth import Principal
from app.deps import ContainerDep, PrincipalDep
from app.repositories import conversations as conv_repo
from app.repositories.models import User
from app.settings import AppEnv, AuthProvider

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class DevLoginRequest(BaseModel):
    email: str = Field(pattern=_EMAIL, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    level: Level | None = None


class ProfileUpdate(BaseModel):
    level: Level


def _out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        role=user.role,
        level=Level(user.level) if user.level else None,
    )


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
    return TokenResponse(access_token=token, user=_out(user))


@router.get("/me", response_model=UserOut)
async def me(principal: PrincipalDep, c: ContainerDep) -> UserOut:
    async with c.maker() as session:
        user = await conv_repo.get_user(session, principal.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다")
    return _out(user)


@router.patch("/me", response_model=UserOut)
async def update_me(body: ProfileUpdate, principal: PrincipalDep, c: ContainerDep) -> UserOut:
    async with c.maker() as session:
        user = await conv_repo.set_user_level(session, principal.user_id, body.level.value)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다")
    return _out(user)
