"""STORAGE_PROVIDER=local: 로컬 볼륨(컨테이너 /data/storage)."""

import asyncio
from pathlib import Path

from app.storage.base import Storage, StoredObject, safe_key


class LocalStorage(Storage):
    scheme = "local"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / safe_key(key)).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("저장소 루트 밖 경로")
        return path

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        key = safe_key(key)
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return StoredObject(key=key, uri=f"{self.scheme}://{key}", size=len(data))

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)
