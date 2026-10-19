"""Supabase Storage over its REST API (httpx), using the service role key from the environment.

Fails closed: without SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY nothing is attempted. The key goes in request
headers only. It is never logged, returned, put in a URL or included in an error; error messages are fixed text
plus the HTTP status, never a response body or header.

Signed URLs: the Storage service signs a path-scoped token (the key is not in it). The URL gets a `download`
query parameter, which makes the service answer with `Content-Disposition: attachment`.
"""
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import httpx

from backend.app.storage.base import StorageError, StorageNotConfigured, StorageObjectNotFound, StoredObject

logger = logging.getLogger("cyphward.storage")

BUCKET = "evidence-files"
TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=60.0, pool=5.0)
LIST_PAGE = 100
DELETE_BATCH = 100
MAX_LIST_OBJECTS = 100_000  # a runaway listing stops here instead of looping


def _enc(path: str) -> str:
    return quote(path, safe="/")


class SupabaseStorage:
    def __init__(self, base_url: str, service_key: str, *, transport: Optional[httpx.BaseTransport] = None,
                 bucket: str = BUCKET) -> None:
        self._base = base_url.rstrip("/")
        self._bucket = bucket
        self._client = httpx.Client(
            base_url=f"{self._base}/storage/v1", timeout=TIMEOUT, transport=transport, follow_redirects=False,
            headers={"Authorization": f"Bearer {service_key}", "apikey": service_key})

    @classmethod
    def from_env(cls) -> "SupabaseStorage":
        url = (os.environ.get("SUPABASE_URL") or "").strip()
        key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        if not url or not key:
            raise StorageNotConfigured("File storage is not configured on this server.")
        parsed = urlparse(url)
        loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not parsed.hostname or parsed.scheme not in {"https", "http"} or (parsed.scheme == "http" and not loopback):
            raise StorageNotConfigured("File storage is not configured on this server.")
        return cls(url, key)

    # ── plumbing ──────────────────────────────────────────────────────────────

    def _request(self, method: str, url: str, *, ok_missing: bool = False, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("storage %s failed (%s)", method, type(exc).__name__)
            raise StorageError("The storage service could not be reached.") from None
        if response.status_code == 404 and ok_missing:
            return response
        if response.status_code >= 400:
            logger.warning("storage %s answered %s", method, response.status_code)
            if response.status_code == 404:
                raise StorageObjectNotFound("The file is not in storage.")
            raise StorageError(f"The storage service answered {response.status_code}.")
        return response

    # ── interface ─────────────────────────────────────────────────────────────

    def put(self, path: str, data: bytes, content_type: str) -> None:
        self._request("POST", f"/object/{self._bucket}/{_enc(path)}", content=data,
                      headers={"Content-Type": content_type, "x-upsert": "false", "Cache-Control": "no-store"})

    def create_signed_url(self, path: str, expires_in: int, download_name: str) -> str:
        response = self._request("POST", f"/object/sign/{self._bucket}/{_enc(path)}", json={"expiresIn": int(expires_in)})
        try:
            relative = str(response.json()["signedURL"])
        except (ValueError, KeyError, TypeError):
            raise StorageError("The storage service returned no link.") from None
        if not relative.startswith("/"):
            raise StorageError("The storage service returned an unexpected link.")
        if relative.startswith("/storage/v1/"):
            relative = relative[len("/storage/v1"):]
        joiner = "&" if "?" in relative else "?"
        return f"{self._base}/storage/v1{relative}{joiner}download={quote(download_name, safe='')}"

    def delete(self, path: str) -> None:
        self._request("DELETE", f"/object/{self._bucket}", json={"prefixes": [path]}, ok_missing=True)

    def list_objects(self, prefix: str) -> List[StoredObject]:
        """Recursive listing: Storage lists one folder level at a time, folders have no id."""
        found: List[StoredObject] = []
        pending = [prefix.strip("/")]
        while pending:
            folder = pending.pop()
            offset = 0
            while True:
                response = self._request("POST", f"/object/list/{self._bucket}", ok_missing=True, json={
                    "prefix": folder, "limit": LIST_PAGE, "offset": offset,
                    "sortBy": {"column": "name", "order": "asc"}})
                if response.status_code == 404:
                    break
                try:
                    items = response.json()
                except ValueError:
                    raise StorageError("The storage service returned an unexpected listing.") from None
                if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
                    raise StorageError("The storage service returned an unexpected listing.")
                for item in items:
                    name = str(item.get("name") or "")
                    if not name:
                        continue
                    full = f"{folder}/{name}" if folder else name
                    if item.get("id") is None:
                        pending.append(full)
                    else:
                        found.append(StoredObject(full, _epoch(item.get("created_at"))))
                if len(found) > MAX_LIST_OBJECTS:
                    raise StorageError("The storage listing is too large to process.")
                if len(items) < LIST_PAGE:
                    break
                offset += LIST_PAGE
        return found

    def delete_prefix(self, prefix: str) -> int:
        """Storage has no prefix delete: list, then delete in batches. Repeats until the prefix is empty."""
        removed = 0
        for _ in range(50):
            objects = self.list_objects(prefix)
            if not objects:
                return removed
            for i in range(0, len(objects), DELETE_BATCH):
                batch = [o.path for o in objects[i:i + DELETE_BATCH]]
                self._request("DELETE", f"/object/{self._bucket}", json={"prefixes": batch}, ok_missing=True)
                removed += len(batch)
        raise StorageError("The storage prefix could not be emptied.")

    def bucket_is_private(self) -> Optional[bool]:
        """True/False from the bucket's `public` flag; None when the bucket does not exist."""
        response = self._request("GET", f"/bucket/{self._bucket}", ok_missing=True)
        if response.status_code == 404:
            return None
        try:
            return not bool(response.json().get("public"))
        except (ValueError, AttributeError):
            raise StorageError("The storage service returned an unexpected answer.") from None


def _epoch(value: Any) -> Optional[float]:
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
