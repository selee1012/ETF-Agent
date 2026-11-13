"""인증 어댑터. AUTH_PROVIDER / ADMIN_AUTH(Enum)로만 고른다(공통 규칙 3)."""

from app.auth.base import AdminVerifier, AuthBackend, AuthError, Principal
from app.settings import AdminAuth, AuthProvider, Settings


def build_auth(settings: Settings) -> AuthBackend:
    match settings.auth_provider:
        case AuthProvider.LOCAL:
            from app.auth.local_jwt import LocalJWTAuth

            assert settings.local_jwt_secret is not None  # noqa: S101 (settings가 채움)
            return LocalJWTAuth(
                secret=settings.local_jwt_secret.get_secret_value(),
                ttl_minutes=settings.local_jwt_ttl_minutes,
            )
        case AuthProvider.SUPABASE:
            from app.auth.supabase_jwt import SupabaseJWTAuth

            return SupabaseJWTAuth(jwks_url=settings.supabase_jwks_url)
        case AuthProvider.ENTRA:
            from app.auth.entra_jwt import EntraJWTAuth

            return EntraJWTAuth(
                tenant_id=settings.entra_tenant_id, client_id=settings.entra_client_id
            )


def build_admin_verifier(settings: Settings) -> AdminVerifier:
    match settings.admin_auth:
        case AdminAuth.LOCAL:
            from app.auth.base import RoleAdminVerifier

            return RoleAdminVerifier()
        case AdminAuth.CF_ACCESS:
            from app.auth.cf_access import CloudflareAccessVerifier

            return CloudflareAccessVerifier(
                team_domain=settings.cf_access_team_domain, aud=settings.cf_access_aud
            )


__all__ = [
    "AdminVerifier",
    "AuthBackend",
    "AuthError",
    "Principal",
    "build_admin_verifier",
    "build_auth",
]
