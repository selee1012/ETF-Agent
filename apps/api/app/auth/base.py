"""인증 인터페이스. # P1-API-01"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    email: str
    role: str = "user"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuthError(Exception):
    """토큰이 없거나 유효하지 않음(401)."""


class AuthBackend(ABC):
    @abstractmethod
    async def authenticate(self, token: str) -> Principal:
        """Bearer 토큰 → Principal. 실패 시 AuthError."""

    def issue(self, principal: Principal) -> str:
        """개발용 토큰 발급(local만 지원). 외부 IdP는 클라이언트가 직접 로그인한다."""
        raise NotImplementedError("이 인증 공급자는 서버에서 토큰을 발급하지 않는다")


class AdminVerifier(ABC):
    """운영 화면 접근 검증. local은 role=admin, 배포 시 Cloudflare Access."""

    @abstractmethod
    async def verify(self, principal: Principal | None, headers: Mapping[str, str]) -> bool: ...


class RoleAdminVerifier(AdminVerifier):
    async def verify(self, principal: Principal | None, headers: Mapping[str, str]) -> bool:
        return principal is not None and principal.is_admin
