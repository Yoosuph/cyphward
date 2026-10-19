"""File storage for evidence files: `get_storage()` is the one way in; tests install a MemoryStorage."""
from typing import Optional

from backend.app.storage.base import Storage, StorageError, StorageNotConfigured, StorageObjectNotFound, StoredObject
from backend.app.storage.supabase import BUCKET, SupabaseStorage

_override: Optional[Storage] = None
_cached: Optional[tuple] = None


def set_storage(storage: Optional[Storage]) -> None:
    """Install (or clear, with None) the storage every call uses. Tests install the in-memory fake."""
    global _override
    _override = storage


def get_storage() -> Storage:
    global _cached
    if _override is not None:
        return _override
    import os
    marker = (os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    if _cached is None or _cached[0] != marker:
        _cached = (marker, SupabaseStorage.from_env())
    return _cached[1]


def is_configured() -> bool:
    try:
        get_storage()
        return True
    except StorageNotConfigured:
        return False


__all__ = ["BUCKET", "Storage", "StorageError", "StorageNotConfigured", "StorageObjectNotFound", "StoredObject",
           "SupabaseStorage", "get_storage", "is_configured", "set_storage"]
