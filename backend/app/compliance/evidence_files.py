"""Evidence file rules (packet C6): what may be attached to a questionnaire answer. Pure functions, no I/O.

Four types only: PDF, PNG, JPG/JPEG and DOCX, at most 10 MB. A file is accepted only when its extension and its
bytes agree (magic bytes; a DOCX must be a small, well-formed zip with a Word main part). The stored content type
comes from the validated type, never from the client. The original name is cleaned and kept only as a display name.
Nothing here says a file proves anything: an attachment is something the customer chose to attach.
"""
import io
import re
import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import Optional, Tuple

MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 100
MAX_TOTAL_BYTES = 500 * 1024 * 1024
UPLOADS_PER_HOUR = 30
RATE_WINDOW_SECONDS = 3600
SIGNED_URL_SECONDS = 60
NAME_MAX = 120
BUCKET = "evidence-files"

ALLOWED_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
EXTENSIONS = {"pdf": "pdf", "png": "png", "jpg": "jpeg", "jpeg": "jpeg", "docx": "docx"}
TYPE_LABELS = {"pdf": "PDF", "png": "PNG image", "jpeg": "JPEG image", "docx": "Word document (DOCX)"}

PDF_MAGIC = b"%PDF-"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
DOCX_MAX_ENTRIES = 1000
DOCX_MAX_UNCOMPRESSED = 50 * 1024 * 1024
DOCX_MAX_RATIO = 100
DOCX_CONTENT_TYPES_MAX = 1024 * 1024
DOCX_MAX_DIRECTORY_BYTES = 256 * 1024  # the zip's central directory; bounds the work of reading it

ALLOWED_TEXT = "PDF, PNG, JPG/JPEG or DOCX files up to 10 MB"


class FileRejected(ValueError):
    """The file cannot be stored. The message says why in plain words; the API maps it to 422 (413 for size)."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Checked:
    display_name: str
    kind: str          # pdf | png | jpeg | docx
    content_type: str  # derived from kind, never from the client


_STRIPPED = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}  # controls, bidi and zero-width (Cf), line separators
_WINDOWS_BAD = re.compile(r'[<>:"|?*\\/]')
_INNER_EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,5}(?=\.|$)")


def clean_name(raw: str) -> str:
    """A safe display name: no path, control, bidi or zero-width characters; at most NAME_MAX characters."""
    text = unicodedata.normalize("NFC", raw or "")
    text = re.split(r"[\\/]", text.replace("\x00", ""))[-1]  # the last path segment only
    text = "".join(ch for ch in text if unicodedata.category(ch) not in _STRIPPED)
    text = _WINDOWS_BAD.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip().strip(".").strip()
    if len(text) > NAME_MAX:
        stem, dot, ext = text.rpartition(".")
        if dot and 1 <= len(ext) <= 8:
            text = stem[: NAME_MAX - len(ext) - 1].rstrip() + "." + ext
        else:
            text = text[:NAME_MAX]
    return text


def check_name(raw: str) -> Tuple[str, str]:
    """(display_name, kind) for an allowed name, else FileRejected. Looks only at the name."""
    if not raw or not raw.strip():
        raise FileRejected("The file needs a name.")
    name = clean_name(raw)
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem.strip():
        raise FileRejected(f"Only {ALLOWED_TEXT} can be attached.")
    kind = EXTENSIONS.get(ext.lower())
    if kind is None:
        raise FileRejected(f"Only {ALLOWED_TEXT} can be attached.")
    # report.pdf.exe is refused by the extension; report.exe.pdf and a.b.pdf are refused here.
    if _INNER_EXTENSION.search(stem):
        raise FileRejected("File names with a second extension (such as report.exe.pdf) are not accepted. Rename the file.")
    return name, kind


def _directory_problem(data: bytes) -> Optional[str]:
    """Refuse a zip whose directory is too big BEFORE it is parsed: the entry count and directory size come from
    the end-of-central-directory record, so the work done on a hostile file is bounded."""
    tail = data[-(65535 + 22):]
    at = tail.rfind(b"PK\x05\x06")
    if at < 0 or len(tail) - at < 22:
        return "This is not a valid DOCX file."
    entries, size = struct.unpack("<HI", tail[at + 10:at + 10 + 2] + tail[at + 12:at + 16])
    if entries == 0xFFFF or size == 0xFFFFFFFF or entries > DOCX_MAX_ENTRIES:
        return "This DOCX file has too many parts to accept."
    if size > DOCX_MAX_DIRECTORY_BYTES:
        return "This DOCX file has too many parts to accept."
    return None


def _docx_problem(data: bytes) -> Optional[str]:
    problem = _directory_problem(data)
    if problem:
        return problem
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        return "This is not a valid DOCX file."
    with archive:
        infos = archive.infolist()
        if len(infos) > DOCX_MAX_ENTRIES:
            return "This DOCX file has too many parts to accept."
        names = [i.filename for i in infos]
        if any(n.startswith(("/", "\\")) or ".." in n.split("/") for n in names):
            return "This is not a valid DOCX file."
        total = sum(i.file_size for i in infos)
        if total > DOCX_MAX_UNCOMPRESSED or total > DOCX_MAX_RATIO * max(len(data), 1):
            return "This DOCX file expands to an unsafe size, so it was not accepted."
        if any(i.flag_bits & 0x1 for i in infos):
            return "Password-protected DOCX files cannot be attached."
        if "[Content_Types].xml" not in names or not any(n.startswith("word/") for n in names):
            return "This is not a valid DOCX file."
        try:
            with archive.open("[Content_Types].xml") as part:
                content_types = part.read(DOCX_CONTENT_TYPES_MAX + 1)
        except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError):
            return "This is not a valid DOCX file."
    if len(content_types) > DOCX_CONTENT_TYPES_MAX:
        return "This is not a valid DOCX file."
    if b"wordprocessingml.document.main" not in content_types:
        return "This is not a valid DOCX file."
    if b"macroEnabled" in content_types:
        return "Macro-enabled documents cannot be attached."
    return None


def check_content(kind: str, data: bytes) -> None:
    """Refuse empty, oversize and mismatching bytes."""
    if not data:
        raise FileRejected("The file is empty.")
    if len(data) > MAX_BYTES:
        raise FileRejected("The file is larger than 10 MB.", status=413)
    if kind == "pdf":
        ok = data.startswith(PDF_MAGIC)
    elif kind == "png":
        ok = data.startswith(PNG_MAGIC)
    elif kind == "jpeg":
        ok = data.startswith(JPEG_MAGIC)
    elif kind == "docx":
        if not data.startswith(b"PK\x03\x04"):
            raise FileRejected("This is not a valid DOCX file.")
        problem = _docx_problem(data)
        if problem:
            raise FileRejected(problem)
        return
    else:
        raise FileRejected(f"Only {ALLOWED_TEXT} can be attached.")
    if not ok:
        raise FileRejected(f"The file's contents do not match its {TYPE_LABELS[kind]} name. Check the file and try again.")


def check(raw_name: str, data: bytes) -> Checked:
    name, kind = check_name(raw_name)
    check_content(kind, data)
    return Checked(display_name=name, kind=kind, content_type=ALLOWED_TYPES[kind])


def storage_path(org_id: str, file_id: str) -> str:
    return f"org/{org_id}/{file_id}"


def org_prefix(org_id: str) -> str:
    return f"org/{org_id}/"
