"""The branded (v2) HTML and PDF renderings of a pack document.

Both walk the same neutral document built by `document.build_v2`: a cover page (logo, brand colours,
organisation, title, issue date, pack id), a summary page, the body, and a closing page that carries the
frozen-record line. The PDF puts a footer (short disclaimer, "Prepared with Cyphward") and "Page X of Y" on
every page, including the cover. The HTML repeats the footer on every printed page and numbers printed pages
with CSS page counters (a browser prints them; a scrolling page has no pages to count).

The logo is drawn from the same shapes as `frontend/public/favicon.svg` (an inline SVG in the HTML, vector
paths in the PDF), so the pack needs no image library and no file. Colours are the product's light-theme
tokens from `frontend/src/index.css`. Text is escaped everywhere; the PDF folds characters Helvetica cannot
print exactly as the v1 renderer does. Table cells cannot split across PDF pages, so every cell the document
builds is bounded (see `document.py`).
"""
import io
from html import escape
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from backend.app.packs import render

DAGGER = "\u2020"  # in Windows-1252, so Helvetica prints it; the shared v1 folding (render.pdf_text) is left exactly as it was


def pdf_text(value: str) -> str:
    """render.pdf_text, except that the legend's dagger survives (branded PDFs only)."""
    return DAGGER.join(render.pdf_text(part) for part in value.split(DAGGER))


def unprintable(value: str) -> bool:
    """True when the PDF font cannot show some of the letters (they would print as '?')."""
    return any(ch != "?" and render.pdf_text(ch) == "?" for ch in value if ch != DAGGER)

# Product tokens (frontend/src/index.css, light theme) and the brighter accent used on the dark band.
INK, SOFT, LINE, INSET, BG = "#12110D", "#575244", "#E2DCCE", "#EFEBE0", "#F8F6F0"
ACCENT, ACCENT_DEEP, ACCENT_BRIGHT, OK, WARN = "#C63A14", "#A02E0F", "#E5532B", "#1E6B37", "#A16A16"
STATUS_COLOUR = {"Evidence present": OK, "Gap": ACCENT_DEEP, "Awaiting your input": WARN, "Upcoming check": WARN,
                 "Not assessed": SOFT, "Not applicable": SOFT}

# The shield mark from favicon.svg, in its 36 x 36 box: outer shield, inner shield, diamond.
OUTER = [("M", 18, 2.5), ("L", 30.5, 7.5), ("L", 30.5, 17.2), ("C", 30.5, 24.8, 25.1, 31.4, 18, 33.5),
         ("C", 10.9, 31.4, 5.5, 24.8, 5.5, 17.2), ("L", 5.5, 7.5)]
INNER = [("M", 18, 7.8), ("L", 26.2, 11.2), ("L", 26.2, 17.4), ("C", 26.2, 22.4, 22.7, 26.8, 18, 28.5),
         ("C", 13.3, 26.8, 9.8, 22.4, 9.8, 17.4), ("L", 9.8, 11.2)]
DIAMOND = [("M", 18, 13.5), ("L", 22, 18), ("L", 18, 22.5), ("L", 14, 18)]


def _svg_path(points) -> str:
    out = []
    for p in points:
        out.append(f"{p[0]} " + " ".join(f"{v:g}" for v in p[1:]))
    return " ".join(out) + " Z"


LOGO_SVG = (f'<svg class="logo" viewBox="0 0 36 36" width="64" height="64" role="img" aria-label="Cyphward logo" '
            f'xmlns="http://www.w3.org/2000/svg" fill="none">'
            f'<path d="{_svg_path(OUTER)}" stroke="{ACCENT_BRIGHT}" stroke-width="2" stroke-linejoin="round"/>'
            f'<path d="{_svg_path(INNER)}" fill="{ACCENT_BRIGHT}" fill-opacity=".35" stroke="{ACCENT_BRIGHT}" '
            f'stroke-width="1.2" stroke-linejoin="round"/>'
            f'<path d="{_svg_path(DIAMOND)}" fill="#FFE4DC" stroke="{ACCENT_BRIGHT}" stroke-width="1"/></svg>')

# ── HTML ─────────────────────────────────────────────────────────────────

def _css(footer: str) -> str:
    quoted = '"' + footer.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'
    return _CSS.replace("@FOOTER@", quoted)


_CSS = f"""
:root{{--ink:{INK};--soft:{SOFT};--line:{LINE};--inset:{INSET};--bg:{BG};--accent:{ACCENT};--deep:{ACCENT_DEEP}}}
*{{box-sizing:border-box}}
body{{font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:#fff;margin:0;
line-height:1.5;font-size:14px}}
.page{{max-width:980px;margin:0 auto;padding:28px 20px}}
.cover{{padding:0 0 28px;max-width:980px;margin:0 auto}}
.band{{background:var(--ink);color:#F8F6F0;padding:36px 32px 30px;border-bottom:6px solid {ACCENT_BRIGHT}}}
.brand{{display:flex;align-items:center;gap:14px;font-weight:700;font-size:22px;letter-spacing:.02em}}
.band h1{{font-family:Georgia,'Times New Roman',serif;font-size:34px;line-height:1.15;margin:46px 0 0;font-weight:700}}
.cover .org{{font-family:Georgia,'Times New Roman',serif;font-size:26px;font-weight:700;margin:34px 32px 6px}}
.cover .prepared{{color:var(--soft);font-size:12px;letter-spacing:.08em;text-transform:uppercase;margin:34px 32px 0}}
.cover dl{{margin:14px 32px 0}}
h2{{font-family:Georgia,'Times New Roman',serif;font-size:21px;margin:26px 0 8px;padding-bottom:4px;
border-bottom:2px solid var(--accent)}}
h2,h3{{break-after:avoid}}
h3{{font-size:14px;color:var(--deep);margin:20px 0 6px}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}
th,td{{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top;font-size:12.5px}}
th{{background:var(--inset);border-bottom:2px solid var(--accent)}}
tr{{break-inside:avoid}}
dt{{font-size:11px;font-weight:700;color:var(--soft);text-transform:uppercase;letter-spacing:.06em;margin-top:10px}}
dd{{margin:0 0 4px;overflow-wrap:anywhere}}
.notice,.legend{{background:#FAF7F0;border:1px solid var(--line);border-left:4px solid var(--accent);padding:10px 14px;
margin:8px 0}}
.stats{{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}}
.stat{{flex:1 1 120px;background:var(--inset);border:1px solid var(--line);padding:10px 12px}}
.stat b{{display:block;font-family:Georgia,'Times New Roman',serif;font-size:26px;line-height:1.1}}
.stat span{{font-size:12px;color:var(--soft)}}
.s-present{{color:{OK};font-weight:600}}.s-gap{{color:{ACCENT_DEEP};font-weight:600}}
.s-await{{color:{WARN};font-weight:600}}.s-na{{color:var(--soft);font-weight:600}}
.mono{{font-family:ui-monospace,Menlo,Consolas,monospace;overflow-wrap:anywhere}}
.pagebreak{{break-before:page}}
.pagefoot{{margin:36px auto 0;max-width:980px;border-top:1px solid var(--line);padding:8px 20px;font-size:11px;
color:var(--soft)}}
@page{{size:A4;margin:16mm 14mm 24mm;
@bottom-left{{content:@FOOTER@;font-size:7.5pt;color:{SOFT};vertical-align:top;padding-top:4mm;width:78%}}
@bottom-right{{content:"Page " counter(page) " of " counter(pages);font-size:7.5pt;color:{SOFT};vertical-align:top;
padding-top:4mm}}}}
@media print{{
.pagefoot{{display:none}}
.band,.stat,th,.notice,.legend{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
}}
@media (max-width:640px){{.band h1{{font-size:26px}}.cover .org{{font-size:21px}}}}
"""


def _status_class(label: str) -> str:
    return {"Evidence present": "s-present", "Gap": "s-gap", "Awaiting your input": "s-await",
            "Upcoming check": "s-await"}.get(label, "s-na")


def _cell(value: str, column: str) -> str:
    text = escape(value).replace("\n", "<br>")
    return f'<span class="{_status_class(value)}">{text}</span>' if column == "Status" else text


def _html_blocks(blocks: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for block in blocks:
        kind = block["type"]
        if kind == "heading":
            tag = "h3" if block.get("level") == 3 else "h2"
            out.append(f"<{tag}>{escape(block['text'])}</{tag}>")
        elif kind == "para":
            out.append(f"<p>{escape(block['text'])}</p>")
        elif kind == "notice":
            out.append(f'<p class="notice">{escape(block["text"])}</p>')
        elif kind == "legend":
            out.append(f'<p class="legend">{escape(block["text"])}</p>')
        elif kind == "bullets":
            out.append("<ul>" + "".join(f"<li>{escape(t)}</li>" for t in block["items"]) + "</ul>")
        elif kind == "facts":
            out.append("<dl>" + "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in block["rows"]) + "</dl>")
        elif kind == "stats":
            out.append('<div class="stats">' + "".join(
                f'<div class="stat"><b>{n}</b><span>{escape(label)}</span></div>' for label, n in block["items"]) + "</div>")
        elif kind == "table":
            head = "".join(f"<th>{escape(h)}</th>" for h in block["head"])
            rows = "".join("<tr>" + "".join(f"<td>{_cell(c, block['head'][i])}</td>" for i, c in enumerate(row)) + "</tr>"
                           for row in block["rows"])
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
    return out


def to_html(doc: Dict[str, Any]) -> str:
    cover = doc["cover"]
    footer = f'{escape(doc["footer"])} {escape(doc["prepared"])}'
    out = ["<!doctype html>", '<html lang="en">', '<head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           f'<title>{escape(doc["title"])} - {escape(cover["org"])}</title><style>{_css(doc['footer'] + ' ' + doc['prepared'])}</style></head><body>',
           '<section class="cover"><div class="band">',
           f'<div class="brand">{LOGO_SVG}<span>Cyphward</span></div>',
           f'<h1>{escape(doc["title"])}</h1></div>',
           f'<p class="prepared">Prepared for</p><p class="org">{escape(cover["org"])}</p>',
           "<dl>", f'<dt>Issued</dt><dd>{escape(cover["issued"])}</dd>',
           f'<dt>Pack ID</dt><dd class="mono">{escape(cover["pack_id"])}</dd>',
           f'<dt>Register version</dt><dd>{escape(cover["register"])}</dd>', "</dl></section>",
           '<section class="page pagebreak">'] + _html_blocks(doc["summary"]) + ["</section>",
           '<section class="page pagebreak">'] + _html_blocks(doc["blocks"]) + ["</section>",
           '<section class="page pagebreak">'] + _html_blocks(doc["closing"]) + [
           f'<div class="pagefoot">{footer}</div></section>', "</body></html>"]
    return "\n".join(out) + "\n"


# ── PDF ──────────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
FOOT = 22 * mm          # bottom margin; the footer lives in it
CONTENT_W = PAGE_W - 2 * MARGIN
BAND_H = 92 * mm


def _c(value: str):
    return colors.HexColor(value)


def _shield(c, x: float, y: float, size: float) -> None:
    """Draw the logo with its 36 x 36 box's lower-left corner at (x, y)."""
    k = size / 36.0

    def trace(points, fill, stroke, width):
        path = c.beginPath()
        for p in points:
            pts = [(x + p[i] * k, y + (36 - p[i + 1]) * k) for i in range(1, len(p), 2)]
            flat = [v for pt in pts for v in pt]
            (path.moveTo if p[0] == "M" else path.lineTo if p[0] == "L" else path.curveTo)(*flat)
        path.close()
        c.setLineWidth(width * k)
        c.setLineJoin(1)
        c.drawPath(path, fill=fill, stroke=stroke)

    c.saveState()
    c.setStrokeColor(_c(ACCENT_BRIGHT))
    c.setFillColor(_c("#6E2A17"))  # the accent at about a third strength on the dark band
    trace(OUTER, 0, 1, 2)
    trace(INNER, 1, 1, 1.2)
    c.setFillColor(_c("#FFE4DC"))
    trace(DIAMOND, 1, 1, 1)
    c.restoreState()


class NumberedCanvas(pdfcanvas.Canvas):
    """Two passes: every page waits until the page count is known, then gets "Page X of Y"."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._states: List[dict] = []

    def showPage(self):
        self._states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._states)
        for state in self._states:
            self.__dict__.update(state)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(_c(SOFT))
            self.drawRightString(PAGE_W - MARGIN, 9.6 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def _styles() -> Dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=13, textColor=_c(INK), alignment=TA_LEFT)
    cell = ParagraphStyle("cell", parent=base, fontSize=8, leading=10.2)
    return {
        "base": base, "cell": cell, "head": ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold"),
        "h2": ParagraphStyle("h2", parent=base, fontName="Times-Bold", fontSize=17, leading=21, spaceBefore=4,
                             spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=13,
                             textColor=_c(ACCENT_DEEP), spaceBefore=8, spaceAfter=3),
        "org": ParagraphStyle("org", parent=base, fontName="Times-Bold", fontSize=22, leading=26),
        "label": ParagraphStyle("label", parent=base, fontName="Helvetica-Bold", fontSize=7.5, leading=10,
                                textColor=_c(SOFT)),
        "notice": ParagraphStyle("notice", parent=base, fontSize=9, leading=12.5),
        "num": ParagraphStyle("num", parent=base, fontName="Times-Bold", fontSize=21, leading=24),
        "tile": ParagraphStyle("tile", parent=base, fontSize=8, leading=10, textColor=_c(SOFT)),
    }


def _p(text: str, style: ParagraphStyle, colour: str = "") -> Paragraph:
    body = escape(pdf_text(text)).replace("\n", "<br/>")
    return Paragraph(f'<font color="{colour}">{body}</font>' if colour else body, style)


def _grid(extra=None) -> TableStyle:
    return TableStyle([("GRID", (0, 0), (-1, -1), 0.4, _c(LINE)), ("BACKGROUND", (0, 0), (-1, 0), _c(INSET)),
                       ("LINEBELOW", (0, 0), (-1, 0), 1.2, _c(ACCENT)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                       ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                       ("LEFTPADDING", (0, 0), (-1, -1), 4.5), ("RIGHTPADDING", (0, 0), (-1, -1), 4.5)] + (extra or []))


def _flowables(blocks: List[Dict[str, Any]], st: Dict[str, ParagraphStyle]) -> List[Any]:
    story: List[Any] = []
    for block in blocks:
        kind = block["type"]
        if kind == "heading":
            story.append(CondPageBreak(40 * mm))
            story.append(_p(block["text"], st["h3"] if block.get("level") == 3 else st["h2"]))
        elif kind == "para":
            story += [_p(block["text"], st["base"]), Spacer(1, 2 * mm)]
        elif kind in ("notice", "legend"):
            box = Table([[_p(block["text"], st["notice"])]], colWidths=[CONTENT_W])
            box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _c("#FAF7F0")),
                                     ("BOX", (0, 0), (-1, -1), 0.4, _c(LINE)),
                                     ("LINEBEFORE", (0, 0), (0, -1), 3, _c(ACCENT)),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            story += [box, Spacer(1, 2.5 * mm)]
        elif kind == "bullets":
            story += [_p("- " + t, st["base"]) for t in block["items"]] + [Spacer(1, 1 * mm)]
        elif kind == "facts":
            rows = [[_p(k.upper(), st["label"]), _p(v, st["base"])] for k, v in block["rows"]]
            facts = Table(rows, colWidths=[CONTENT_W * 0.24, CONTENT_W * 0.76])
            facts.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, _c(LINE)),
                                       ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            story += [facts, Spacer(1, 2 * mm)]
        elif kind == "stats":
            items = block["items"]
            tiles = Table([[[_p(str(n), st["num"], ACCENT_DEEP if label == "Gaps" and n else ""),
                             _p(label, st["tile"])] for label, n in items]], colWidths=[CONTENT_W / len(items)] * len(items))
            tiles.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _c(INSET)), ("BOX", (0, 0), (-1, -1), 0.4, _c(LINE)),
                                       ("INNERGRID", (0, 0), (-1, -1), 0.4, _c(LINE)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                       ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
            story += [tiles, Spacer(1, 3 * mm)]
        elif kind == "table":
            head = block["head"]
            cols = len(head)
            weights = ([1.0] * cols if cols < 4 else [1.45, 0.85, 0.85, 2.3] + [1.0] * (cols - 4)) if cols != 5 else \
                [0.55, 1.5, 0.9, 1.6, 1.8]
            if head[:1] == ["Priority"] and cols == 4:
                weights = [0.6, 1.8, 1.0, 2.4]
            rows = [[_p(h, st["head"]) for h in head]]
            for row in block["rows"]:
                rows.append([_p(c, st["cell"], STATUS_COLOUR.get(c, "") if head[i] == "Status" else "")
                             for i, c in enumerate(row)])
            table = Table(rows, colWidths=[CONTENT_W * w / sum(weights) for w in weights], repeatRows=1)
            table.setStyle(_grid())
            story += [table, Spacer(1, 2.5 * mm)]
    return story


def to_pdf(doc: Dict[str, Any]) -> bytes:
    st = _styles()
    cover = doc["cover"]
    title = pdf_text(doc["title"])
    footer, prepared = pdf_text(doc["footer"]), pdf_text(doc["prepared"])

    def draw_footer(c, d):
        c.saveState()
        c.setStrokeColor(_c(LINE))
        c.setLineWidth(0.5)
        c.line(MARGIN, 16.5 * mm, PAGE_W - MARGIN, 16.5 * mm)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(_c(SOFT))
        c.drawString(MARGIN, 13.2 * mm, footer)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(MARGIN, 9.6 * mm, prepared)
        c.restoreState()

    def on_cover(c, d):
        c.saveState()
        c.setFillColor(_c(INK))
        c.rect(0, PAGE_H - BAND_H, PAGE_W, BAND_H, stroke=0, fill=1)
        c.setFillColor(_c(ACCENT_BRIGHT))
        c.rect(0, PAGE_H - BAND_H - 2 * mm, PAGE_W, 2 * mm, stroke=0, fill=1)
        _shield(c, MARGIN, PAGE_H - 36 * mm, 17 * mm)
        c.setFillColor(_c(BG))
        c.setFont("Helvetica-Bold", 20)
        c.drawString(MARGIN + 21 * mm, PAGE_H - 26.5 * mm, "Cyphward")
        c.setFont("Times-Bold", 29)
        for n, line in enumerate(simpleSplit(title, "Times-Bold", 29, CONTENT_W)):
            c.drawString(MARGIN, PAGE_H - 62 * mm - n * 33, line)
        c.restoreState()
        draw_footer(c, d)

    def on_page(c, d):
        draw_footer(c, d)
        c.saveState()
        c.setFillColor(_c(ACCENT_BRIGHT))
        c.rect(0, PAGE_H - 3 * mm, PAGE_W, 3 * mm, stroke=0, fill=1)
        c.restoreState()

    buffer = io.BytesIO()
    pdf = BaseDocTemplate(buffer, pagesize=A4, title=title, author="Cyphward", subject=f"Pack {doc['pack_id']}",
                          invariant=1, pageCompression=0, leftMargin=MARGIN, rightMargin=MARGIN)
    cover_frame = Frame(MARGIN, FOOT, CONTENT_W, PAGE_H - BAND_H - 12 * mm - FOOT, id="cover", leftPadding=0,
                        rightPadding=0, topPadding=0, bottomPadding=0)
    body_frame = Frame(MARGIN, FOOT, CONTENT_W, PAGE_H - 14 * mm - FOOT, id="body", leftPadding=0, rightPadding=0,
                       topPadding=0, bottomPadding=0)
    pdf.addPageTemplates([PageTemplate("cover", [cover_frame], onPage=on_cover),
                          PageTemplate("body", [body_frame], onPage=on_page)])
    facts = [("Issued", cover["issued"]), ("Pack ID", cover["pack_id"]), ("Register version", cover["register"])]
    lossy = unprintable(cover["org"])
    org_pdf = "".join(ch for ch in cover["org"] if ch == "?" or not unprintable(ch)) if lossy else cover["org"]
    org_pdf = " ".join(render.pdf_text(org_pdf).split()) if lossy else org_pdf
    story: List[Any] = [Spacer(1, 4 * mm), _p("PREPARED FOR", st["label"]), Spacer(1, 2 * mm),
                        _p(org_pdf or "Organisation (name shown in the HTML version)", st["org"])]
    if lossy:
        story += [Spacer(1, 2 * mm), _p("The organisation name contains characters this PDF font cannot show. "
                                        "The HTML version of this pack shows it in full.", st["label"])]
    story += [Spacer(1, 9 * mm), _flowables([{"type": "facts", "rows": facts}], st)[0],
                        NextPageTemplate("body"), PageBreak()]
    summary = [dict(b, rows=[(k, org_pdf if k == "Organisation" else v) for k, v in b["rows"]]) if b["type"] == "facts"
               else b for b in doc["summary"]]
    story += _flowables(summary, st) + [PageBreak()] + _flowables(doc["blocks"], st) + [PageBreak()]
    story += [KeepTogether(_flowables(doc["closing"], st))]
    pdf.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()
