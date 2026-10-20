"""In-memory storage used by every test. Thread-safe; can be told to fail."""
import secrets
import threading
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from backend.app.storage.base import StorageError, StorageObjectNotFound, StoredObject


class MemoryStorage:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.objects: Dict[str, Tuple[bytes, str, float]] = {}
        self.signed: List[Dict[str, object]] = []
        self.fail_put = False
        self.fail_delete = False
        self.fail_delete_prefix = False
        self.fail_sign = False
        self.put_delay = 0.0
        self.calls: List[Tuple[str, str]] = []

    def put(self, path: str, data: bytes, content_type: str) -> None:
        if self.put_delay:
            time.sleep(self.put_delay)
        with self._lock:
            self.calls.append(("put", path))
            if self.fail_put:
                raise StorageError("The storage service could not store the file.")
            if path in self.objects:
                raise StorageError("The storage service refused to overwrite an object.")
            self.objects[path] = (bytes(data), content_type, time.time())

    def create_signed_url(self, path: str, expires_in: int, download_name: str) -> str:
        with self._lock:
            self.calls.append(("sign", path))
            if self.fail_sign:
                raise StorageError("The storage service could not create a link.")
            if path not in self.objects:
                raise StorageObjectNotFound("The file is not in storage.")
            token = secrets.token_urlsafe(24)
            self.signed.append({"path": path, "expires_in": expires_in, "download_name": download_name})
        return (f"https://storage.invalid/storage/v1/object/sign/evidence-files/{path}"
                f"?token={token}&download={quote(download_name)}")

    def delete(self, path: str) -> None:
        with self._lock:
            self.calls.append(("delete", path))
            if self.fail_delete:
                raise StorageError("The storage service could not delete the file.")
            self.objects.pop(path, None)

    def delete_prefix(self, prefix: str) -> int:
        with self._lock:
            self.calls.append(("delete_prefix", prefix))
            if self.fail_delete_prefix:
                raise StorageError("The storage service could not delete the files.")
            doomed = [p for p in self.objects if p.startswith(prefix)]
            for p in doomed:
                del self.objects[p]
            return len(doomed)

    def list_objects(self, prefix: str) -> List[StoredObject]:
        with self._lock:
            return [StoredObject(p, v[2]) for p, v in sorted(self.objects.items()) if p.startswith(prefix)]

    # test helpers
    def age(self, path: str, seconds: float) -> None:
        with self._lock:
            data, ctype, created = self.objects[path]
            self.objects[path] = (data, ctype, created - seconds)

    def call_names(self, name: Optional[str] = None) -> List[str]:
        with self._lock:
            return [p for n, p in self.calls if name is None or n == name]
