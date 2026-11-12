"""저장소 인터페이스. 키는 'uploads/2026/11/파일명' 같은 상대 경로다."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

_SAFE = re.compile(r"[^0-9A-Za-z가-힣._/-]+")


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    uri: str  # documents.source_uri로 쓴다(예: local://uploads/a.md)
    size: int


def safe_key(key: str) -> str:
    """경로 조작(.., 절대경로)을 막고 허용 문자만 남긴다."""
    parts = [p for p in _SAFE.sub("_", key).split("/") if p not in ("", ".", "..")]
    if not parts:
        raise ValueError("빈 저장소 키")
    return "/".join(parts)


class Storage(ABC):
    scheme: str

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject: ...

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...
