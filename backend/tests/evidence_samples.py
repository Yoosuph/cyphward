"""Small valid sample files for the evidence-file tests (no network, no disk)."""
import io
import zipfile

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32

CONTENT_TYPES = (b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 b'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                 b'wordprocessingml.document.main+xml"/></Types>')


def docx(extra=None, content_types=CONTENT_TYPES, compress=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compress) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("word/document.xml", b"<w:document/>")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


DOCX = docx()
SAMPLES = {"pdf": ("policy.pdf", PDF), "png": ("scan.png", PNG), "jpg": ("photo.jpg", JPEG), "docx": ("minutes.docx", DOCX)}
