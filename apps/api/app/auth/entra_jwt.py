"""AUTH_PROVIDER=entra 스텁(Phase 2). Microsoft Entra External ID가 발급한 JWT 검증 자리."""

from app.auth.base import AuthBackend, Principal


class EntraJWTAuth(AuthBackend):
    def __init__(self, *, tenant_id: str | None, client_id: str | None) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id

    async def authenticate(self, token: str) -> Principal:
        # 구현 시: 테넌트의 OpenID 설정(.well-known/openid-configuration)에서 jwks_uri를 읽어
        # PyJWKClient로 서명 검증, aud=client_id·iss 확인, sub → users 매핑
        raise NotImplementedError("Entra External ID 검증은 Phase 2에서 구현한다")
