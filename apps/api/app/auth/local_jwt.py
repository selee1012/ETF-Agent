"""AUTH_PROVIDER=local: 개발용 HS256 JWT. APP_ENV=local에서만 dev-login이 열린다. # P1-API-01"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.auth.base import AuthBackend, AuthError, Principal

_ISSUER = "etf-agent-local"


class LocalJWTAuth(AuthBackend):
    def __init__(self, *, secret: str, ttl_minutes: int) -> None:
        self._secret = secret
        self._ttl = timedelta(minutes=ttl_minutes)

    def issue(self, principal: Principal) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": str(principal.user_id),
            "email": principal.email,
            "role": principal.role,
            "iss": _ISSUER,
            "iat": now,
            "exp": now + self._ttl,
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")

    async def authenticate(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=_ISSUER,
                options={"require": ["sub", "exp", "iss"]},
            )
            return Principal(
                user_id=uuid.UUID(claims["sub"]),
                email=str(claims.get("email", "")),
                role=str(claims.get("role", "user")),
            )
        except (jwt.PyJWTError, ValueError) as e:
            raise AuthError("유효하지 않은 토큰") from e
