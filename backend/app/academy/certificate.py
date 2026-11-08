"""Completion certificates: the public code, the reviewed wording and the branded PDF.

Wording rule (test_academy.py): a certificate says the person COMPLETED the course. It never says the person or the
organisation is certified, accredited or compliant, and the verification page shows only the learner's name, the
course title and the completion date.

The PDF uses reportlab like the evidence packs (packs/render.py): built-in Helvetica, uncompressed, invariant, so
`render.pdf_extract_text` can read it back in tests. Names outside Latin-1 are folded the same way as in the packs.
"""
import io
import textwrap
import secrets
from datetime import datetime
from typing import Any, Dict, Mapping

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from backend.app.packs.render import pdf_text

# No 0/O, 1/I: codes are read aloud and typed from paper.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
VERIFY_BASE = "https://academy.cyphward.com/verify/"

HEADING = "Certificate of completion"
COMPLETED_LINE = "has completed the course"
FOOTNOTE = ("This certificate records that the person named above completed every lesson and passed every quiz of "
            "this Cyphward Academy course. It describes course completion only.")
VERIFY_NOTE = "Check this certificate at"
PUBLIC_FIELDS = ("code", "learner_name", "course_title", "completed_on")

INK = colors.HexColor("#12110D")
SOFT = colors.HexColor("#575244")
ACCENT = colors.HexColor("#C63A14")
LINE = colors.HexColor("#E2DCCE")
PAPER = colors.HexColor("#F8F6F0")


def new_code() -> str:
    """XXXX-XXXX-XXXX-XXXX from a 32-letter alphabet: 80 random bits, not guessable."""
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(16))
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def normalise_code(value: str) -> str:
    cleaned = "".join(ch for ch in (value or "").upper() if ch.isalnum())
    return "-".join(cleaned[i:i + 4] for i in range(0, 16, 4)) if len(cleaned) == 16 else ""


def display_name(full_name: Any, email: Any = None) -> str:
    """The name printed on a certificate: the profile's name, never the email address."""
    name = " ".join(str(full_name or "").split())[:200]
    return name or "Cyphward learner"


def long_date(value: datetime) -> str:
    return f"{value.day} {value.strftime('%B %Y')}"


def public_view(row: Mapping[str, Any]) -> Dict[str, Any]:
    """The only shape the public verification route returns (exact key set checked in tests)."""
    return {"code": row["code"], "learner_name": row["learner_name"], "course_title": row["course_title"],
            "completed_on": row["completed_at"].date().isoformat()}


def to_pdf(row: Mapping[str, Any]) -> bytes:
    width, height = landscape(A4)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height), invariant=1, pageCompression=0)
    pdf.setTitle(pdf_text(f"Cyphward Academy - {HEADING} - {row['course_title']}"))
    pdf.setAuthor("Cyphward")
    pdf.setFillColor(PAPER)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    pdf.setStrokeColor(LINE)
    pdf.setLineWidth(1.2)
    pdf.rect(28, 28, width - 56, height - 56, stroke=1, fill=0)
    pdf.setFillColor(ACCENT)
    pdf.rect(28, height - 34, width - 56, 6, stroke=0, fill=1)

    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(64, height - 84, "CYPHWARD")
    pdf.setFillColor(SOFT)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(64 + pdf.stringWidth("CYPHWARD ", "Helvetica-Bold", 13), height - 84, "ACADEMY")

    centre = width / 2
    pdf.setFillColor(ACCENT)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawCentredString(centre, height - 170, HEADING.upper())
    pdf.setFillColor(SOFT)
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(centre, height - 205, "This is to record that")
    pdf.setFillColor(INK)
    name = pdf_text(row["learner_name"])
    size = 32
    while size > 16 and pdf.stringWidth(name, "Helvetica-Bold", size) > width - 160:
        size -= 2
    pdf.setFont("Helvetica-Bold", size)
    pdf.drawCentredString(centre, height - 250, name)
    pdf.setFillColor(SOFT)
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(centre, height - 285, COMPLETED_LINE)
    pdf.setFillColor(INK)
    title = pdf_text(row["course_title"])
    tsize = 22
    while tsize > 12 and pdf.stringWidth(title, "Helvetica-Bold", tsize) > width - 160:
        tsize -= 1
    pdf.setFont("Helvetica-Bold", tsize)
    pdf.drawCentredString(centre, height - 320, title)
    pdf.setFillColor(SOFT)
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(centre, height - 352, f"on {long_date(row['completed_at'])}")

    pdf.setStrokeColor(LINE)
    pdf.line(64, 132, width - 64, 132)
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(SOFT)
    for n, part in enumerate(textwrap.wrap(pdf_text(FOOTNOTE), 120)):
        pdf.drawString(64, 110 - 13 * n, part)
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(64, 70, f"Certificate ID {row['code']}")
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(width - 64, 70, f"{VERIFY_NOTE} {VERIFY_BASE}{row['code']}")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
