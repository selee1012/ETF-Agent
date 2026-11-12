"""ADMIN_AUTH=cf_access 스텁(Phase 1 배포). Cf-Access-Jwt-Assertion 헤더 검증 자리."""

from collections.abc import Mapping

from app.auth.base import AdminVerifier, Principal


class CloudflareAccessVerifier(AdminVerifier):
    def __init__(self, *, team_domain: str | None, aud: str | None) -> None:
        self.team_domain = team_domain
        self.aud = aud

    async def verify(self, principal: Principal | None, headers: Mapping[str, str]) -> bool:
        # 구현 시: https://{team_domain}/cdn-cgi/access/certs 로 서명 검증, aud 확인
        raise NotImplementedError("Cloudflare Access 검증은 Phase 1 배포 단계에서 구현한다")
