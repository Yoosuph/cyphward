"""HTML and PDF renderings of a pack document (packet C4).

Both walk the same document, so they carry the same text, source labels and disclaimer. HTML is pure
string building with everything escaped. The PDF uses reportlab (pure Python, no system packages) with
the built-in Helvetica font, uncompressed streams and `invariant=1`; the stored bytes are what is served,
so a download never re-renders. Helvetica covers Latin-1 only: other characters are folded to their ASCII
base letter (a name like "Ọ̀ṣun" prints as "Osun"), and anything left becomes '?'. The HTML keeps the original.
"""
import io
import unicodedata
from html import escape
from typing import Any, Dict

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CSS = ("body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1F1A14;max-width:980px;"
       "margin:24px auto;padding:0 16px;line-height:1.5;font-size:14px}h1{font-size:24px}h2{font-size:18px;margin-top:28px}"
       "h3{font-size:15px}table{border-collapse:collapse;width:100%;margin:8px 0}th,td{border:1px solid #D9D4C8;"
       "padding:6px 8px;text-align:left;vertical-align:top;font-size:12.5px}th{background:#F5F2EC}"
       ".disclaimer{background:#FAF9F6;border:1px solid #EFECE5;border-radius:6px;padding:10px 14px}"
       "dt{font-weight:600}dd{margin:0 0 6px}")


def to_html(doc: Dict[str, Any]) -> str:
    out = ['<!doctype html>', '<html lang="en">', '<head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           f'<title>{escape(doc["title"])}</title><style>{CSS}</style></head><body>', f'<h1>{escape(doc["title"])}</h1>',
           '<dl>']
    for label, value in doc["meta"]:
        out.append(f'<dt>{escape(label)}</dt><dd>{escape(value)}</dd>')
    out.append('</dl>')
    for i, block in enumerate(doc["blocks"]):
        kind = block["type"]
        if kind == "heading":
            tag = "h3" if block.get("level") == 3 else "h2"
            out.append(f'<{tag}>{escape(block["text"])}</{tag}>')
        elif kind == "para":
            cls = ' class="disclaimer"' if i < 2 else ""
            out.append(f'<p{cls}>{escape(block["text"])}</p>')
        elif kind == "bullets":
            out.append('<ul>' + ''.join(f'<li>{escape(t)}</li>' for t in block["items"]) + '</ul>')
        elif kind == "table":
            head = ''.join(f'<th>{escape(h)}</th>' for h in block["head"])
            rows = ''.join('<tr>' + ''.join(f'<td>{escape(c)}</td>' for c in row) + '</tr>' for row in block["rows"])
            out.append(f'<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>')
    out.append('</body></html>')
    return "\n".join(out) + "\n"


PUNCTUATION = {"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
               "\u2026": "...", "\u00b7": "|", "\u2192": "->", "\u2022": "-", "\u00a0": " "}


def pdf_text(value: str) -> str:
    """Fold to what Helvetica can print: Latin-1 as is; other letters to their base ASCII; marks dropped; the rest '?'."""
    out = []
    for ch in value:
        if ch in PUNCTUATION:
            out.append(PUNCTUATION[ch])
        elif unicodedata.combining(ch):
            continue
        elif ord(ch) < 256:
            out.append(ch)
        else:
            base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
            out.append(base if base and all(ord(c) < 256 for c in base) else "?")
    return "".join(out)


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(pdf_text(text)), style)


def to_pdf(doc: Dict[str, Any]) -> bytes:
    sheet = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=sheet["BodyText"], fontName="Helvetica", fontSize=9.5, leading=12.5)
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold")
    h1 = ParagraphStyle("h1", parent=sheet["Heading1"], fontName="Helvetica-Bold", fontSize=18)
    h2 = ParagraphStyle("h2", parent=sheet["Heading2"], fontName="Helvetica-Bold", fontSize=13)
    h3 = ParagraphStyle("h3", parent=sheet["Heading3"], fontName="Helvetica-Bold", fontSize=11)
    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=pdf_text(doc["title"]), author="Cyphward",
                            invariant=1, pageCompression=0)
    story = [_p(doc["title"], h1)]
    for label, value in doc["meta"]:
        story.append(_p(f"{label}: {value}", body))
    story.append(Spacer(1, 4 * mm))
    width = A4[0] - 28 * mm
    for block in doc["blocks"]:
        kind = block["type"]
        if kind == "heading":
            story += [Spacer(1, 3 * mm), _p(block["text"], h3 if block.get("level") == 3 else h2)]
        elif kind == "para":
            story += [_p(block["text"], body), Spacer(1, 2 * mm)]
        elif kind == "bullets":
            story += [_p("- " + t, body) for t in block["items"]]
        elif kind == "table":
            cols = len(block["head"])
            rows = [[_p(h, head) for h in block["head"]]] + [[_p(c, cell) for c in row] for row in block["rows"]]
            weights = [1.0] * cols if cols < 4 else [1.3, 0.8, 0.8, 2.2] + [1.0] * (cols - 4)
            table = Table(rows, colWidths=[width * w / sum(weights) for w in weights], repeatRows=1)
            table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8B2A5")),
                                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5F2EC")),
                                       ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [table, Spacer(1, 2 * mm)]
    pdf.build(story)
    return buffer.getvalue()


def pdf_extract_text(data: bytes) -> str:
    """Text of an uncompressed pack PDF, whitespace collapsed (used by tests and by the integrity check)."""
    import re
    chunks = re.findall(rb"\((?:\\.|[^\\)])*\)\s*Tj", data)
    parts = []
    for chunk in chunks:
        raw = chunk[1:chunk.rindex(b")")]
        raw = re.sub(rb"\\([()\\])", rb"\1", raw)
        parts.append(raw.decode("latin-1"))
    return " ".join(" ".join(parts).split())
