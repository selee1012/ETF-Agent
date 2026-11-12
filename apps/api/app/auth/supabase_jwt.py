"""AUTH_PROVIDER=supabase 스텁(Phase 1 배포). Supabase Auth JWT를 JWKS로 검증할 자리."""

from app.auth.base import AuthBackend, Principal


class SupabaseJWTAuth(AuthBackend):
    def __init__(self, *, jwks_url: str | None) -> None:
        self.jwks_url = jwks_url

    async def authenticate(self, token: str) -> Principal:
        # 구현 시: PyJWKClient(jwks_url)로 서명 검증, aud="authenticated", sub → users 매핑
        raise NotImplementedError("Supabase Auth 검증은 Phase 1 배포 단계에서 구현한다")
