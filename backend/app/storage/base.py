"""The storage interface evidence files go through (and its errors).

Two implementations: `SupabaseStorage` (Supabase Storage REST, service role) and `MemoryStorage` (the fake
every test uses). Callers never see a key, a header or a response body: errors carry a short fixed message.
"""
from dataclasses import dataclass
from typing import List, Optional, Protocol


class StorageError(RuntimeError):
    """A storage call failed. The message is safe to log and to show: it never carries a key, header or body."""


class StorageNotConfigured(StorageError):
    """SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing. Uploads fail closed; the API maps it to 503."""


class StorageObjectNotFound(StorageError):
    """The object does not exist (a signed link cannot be made for it)."""


@dataclass(frozen=True)
class StoredObject:
    path: str
    created_at: Optional[float] = None  # epoch seconds, when the backend reports it


class Storage(Protocol):
    def put(self, path: str, data: bytes, content_type: str) -> None:
        """Store `data` at `path`. Never overwrites an existing object."""

    def create_signed_url(self, path: str, expires_in: int, download_name: str) -> str:
        """A short-lived URL that serves the object as an attachment named `download_name`."""

    def delete(self, path: str) -> None:
        """Delete one object. A missing object is not an error."""

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under `prefix` (for example `org/<id>/`). Returns how many were removed."""

    def list_objects(self, prefix: str) -> List[StoredObject]:
        """Every object under `prefix`, recursively."""
