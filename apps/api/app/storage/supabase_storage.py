"""STORAGE_PROVIDER=supabase 스텁 — Supabase Storage(Phase 1 배포). 구현 시 공급자 SDK는 이 파일에서만 import 한다."""

from app.storage.base import Storage, StoredObject


class SupabaseStorage(Storage):
    scheme = "supabase"

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        raise NotImplementedError("Supabase Storage(Phase 1 배포) 저장소는 아직 구현하지 않았다")

    async def get(self, key: str) -> bytes:
        raise NotImplementedError("Supabase Storage(Phase 1 배포) 저장소는 아직 구현하지 않았다")

    async def delete(self, key: str) -> None:
        raise NotImplementedError("Supabase Storage(Phase 1 배포) 저장소는 아직 구현하지 않았다")

    async def exists(self, key: str) -> bool:
        raise NotImplementedError("Supabase Storage(Phase 1 배포) 저장소는 아직 구현하지 않았다")
