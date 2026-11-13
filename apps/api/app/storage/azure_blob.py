"""STORAGE_PROVIDER=azure_blob 스텁 — Azure Blob Storage(Phase 2). 구현 시 공급자 SDK는 이 파일에서만 import 한다.

원본 파일은 Blob 컨테이너에 두고, DB(documents.source_uri)에는 주소(azure_blob://키)만 남긴다.
"""

from app.storage.base import Storage, StoredObject


class AzureBlobStorage(Storage):
    scheme = "azure_blob"

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        raise NotImplementedError("Azure Blob Storage(Phase 2) 저장소는 아직 구현하지 않았다")

    async def get(self, key: str) -> bytes:
        raise NotImplementedError("Azure Blob Storage(Phase 2) 저장소는 아직 구현하지 않았다")

    async def delete(self, key: str) -> None:
        raise NotImplementedError("Azure Blob Storage(Phase 2) 저장소는 아직 구현하지 않았다")

    async def exists(self, key: str) -> bool:
        raise NotImplementedError("Azure Blob Storage(Phase 2) 저장소는 아직 구현하지 않았다")
