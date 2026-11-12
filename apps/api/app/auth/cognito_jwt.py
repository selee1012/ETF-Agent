"""AUTH_PROVIDER=cognito 스텁(Phase 2). Cognito User Pool JWT 검증 자리."""

from app.auth.base import AuthBackend, Principal


class CognitoJWTAuth(AuthBackend):
    def __init__(self, *, region: str, user_pool_id: str | None) -> None:
        self.region = region
        self.user_pool_id = user_pool_id

    async def authenticate(self, token: str) -> Principal:
        # 구현 시: https://cognito-idp.{region}.amazonaws.com/{pool}/.well-known/jwks.json
        raise NotImplementedError("Cognito 검증은 Phase 2에서 구현한다")
