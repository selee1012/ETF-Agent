"""파일 저장소 어댑터. STORAGE_PROVIDER(Enum)로만 고른다."""

from app.settings import Settings, StorageProvider
from app.storage.base import Storage, StoredObject


def build_storage(settings: Settings) -> Storage:
    match settings.storage_provider:
        case StorageProvider.LOCAL:
            from app.storage.local import LocalStorage

            return LocalStorage(settings.storage_local_dir)
        case StorageProvider.SUPABASE:
            from app.storage.supabase_storage import SupabaseStorage

            return SupabaseStorage()
        case StorageProvider.S3:
            from app.storage.s3 import S3Storage

            return S3Storage()


__all__ = ["Storage", "StoredObject", "build_storage"]
