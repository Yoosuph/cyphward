"""Lesson Markdown, parsed on the server into plain data blocks. Nothing is ever rendered as HTML.

The frontend (frontend/src/academy/LessonBody.tsx) maps each block type to a React element, so text is always escaped
by React and there is no `dangerouslySetInnerHTML` anywhere. Raw HTML in a lesson is kept as literal text.

Supported, deliberately small:
  blocks   heading (## and ###; # is shown as ##), paragraph, bullet and numbered lists, quote, code (fenced ``` or
           indented four spaces), image (a line that is only ![alt](https://...)), rule (---)
  inline   **strong**, *em* / _em_, `code`, [text](url)

Links: only http, https and mailto keep their target; anything else (javascript:, data:, vbscript:, relative paths)
becomes plain text. Images: only https; anything else becomes its alt text. Control characters are removed.
"""
import re
from typing import Any, Dict, List, Optional

MAX_CHARS = 40000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_IMAGE_LINE = re.compile(r"^!\[([^\]]{0,200})\]\(([^)\s]{1,500})\)\s*$")
_LIST_ITEM = re.compile(r"^\s{0,3}([-*+]|\d{1,3}[.)])\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_INLINE = re.compile(
    r"(?P<code>`[^`\n]{1,300}`)"
    r"|(?P<link>\[(?P<ltext>[^\]\n]{1,300})\]\((?P<lhref>[^)\s]{1,500})\))"
    r"|(?P<strong>\*\*(?P<stext>[^*\n]{1,500})\*\*)"
    r"|(?P<em>(?<![\w*])\*(?P<etext>[^*\n]{1,500})\*(?![\w*])|(?<![\w_])_(?P<utext>[^_\n]{1,500})_(?![\w_]))"
)


def clean(text: Optional[str]) -> str:
    """Normalise line endings and drop control characters (tab and newline stay)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL.sub("", text)


def safe_href(href: str) -> Optional[str]:
    value = (href or "").strip()
    lowered = value.lower()
    if lowered.startswith(("https://", "http://")) and len(value) > 8:
        return value
    if lowered.startswith("mailto:") and "@" in value and len(value) > 8:
        return value
    return None


def safe_image(src: str) -> Optional[str]:
    value = (src or "").strip()
    return value if value.lower().startswith("https://") and len(value) > 10 else None


def inline(text: str) -> List[Dict[str, Any]]:
    """Inline nodes for one run of text. Unknown syntax stays as text."""
    out: List[Dict[str, Any]] = []
    pos = 0

    def push_text(value: str) -> None:
        if not value:
            return
        if out and out[-1]["type"] == "text":
            out[-1]["text"] += value
        else:
            out.append({"type": "text", "text": value})

    for match in _INLINE.finditer(text):
        push_text(text[pos:match.start()])
        pos = match.end()
        if match.group("code"):
            out.append({"type": "code", "text": match.group("code")[1:-1]})
        elif match.group("link"):
            href = safe_href(match.group("lhref"))
            label = match.group("ltext")
            if href:
                out.append({"type": "link", "href": href, "text": label})
            else:
                push_text(label)
        elif match.group("strong"):
            out.append({"type": "strong", "text": match.group("stext")})
        else:
            out.append({"type": "em", "text": match.group("etext") or match.group("utext")})
    push_text(text[pos:])
    return out


def to_blocks(markdown: Optional[str]) -> List[Dict[str, Any]]:
    """The lesson body as a list of blocks (see the module docstring)."""
    lines = clean(markdown)[:MAX_CHARS].split("\n")
    blocks: List[Dict[str, Any]] = []
    para: List[str] = []
    i = 0

    def flush() -> None:
        if para:
            blocks.append({"type": "paragraph", "children": inline(" ".join(s.strip() for s in para))})
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush()
            i += 1
            continue
        if stripped.startswith("```"):
            flush()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            blocks.append({"type": "code", "text": "\n".join(body)})
            i += 1
            continue
        if line.startswith("    ") and not para:
            body = []
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                body.append(lines[i][4:])
                i += 1
            while body and not body[-1].strip():
                body.pop()
            blocks.append({"type": "code", "text": "\n".join(body)})
            continue
        heading = _HEADING.match(stripped)
        if heading:
            flush()
            level = 3 if len(heading.group(1)) >= 3 else 2
            blocks.append({"type": "heading", "level": level, "children": inline(heading.group(2))})
            i += 1
            continue
        if _RULE.match(line):
            flush()
            blocks.append({"type": "rule"})
            i += 1
            continue
        image = _IMAGE_LINE.match(stripped)
        if image:
            flush()
            src = safe_image(image.group(2))
            if src:
                blocks.append({"type": "image", "src": src, "alt": image.group(1).strip()})
            elif image.group(1).strip():
                blocks.append({"type": "paragraph", "children": [{"type": "text", "text": image.group(1).strip()}]})
            i += 1
            continue
        if stripped.startswith(">"):
            flush()
            quoted = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quoted.append(lines[i].strip()[1:].lstrip())
                i += 1
            inner = [b for b in to_blocks("\n".join(quoted)) if b["type"] in ("paragraph", "list")]
            blocks.append({"type": "quote", "children": inner})
            continue
        item = _LIST_ITEM.match(line)
        if item:
            flush()
            ordered = item.group(1)[0].isdigit()
            items: List[List[Dict[str, Any]]] = []
            while i < len(lines):
                current = _LIST_ITEM.match(lines[i])
                if current and current.group(1)[0].isdigit() == ordered:
                    items.append([{"type": "text", "text": ""}] if not current.group(2).strip() else inline(current.group(2).strip()))
                    i += 1
                elif lines[i].startswith("  ") and lines[i].strip() and items:
                    items[-1] = inline(_plain(items[-1]) + " " + lines[i].strip())  # a wrapped item line
                    i += 1
                else:
                    break
            blocks.append({"type": "list", "ordered": ordered, "items": items})
            continue
        para.append(line)
        i += 1
    flush()
    return blocks


def _plain(nodes: List[Dict[str, Any]]) -> str:
    return "".join(n.get("text", "") for n in nodes)


def plain_text(markdown: Optional[str]) -> str:
    """Every visible word of a lesson, for the wording checks and search."""
    words: List[str] = []

    def walk(block: Dict[str, Any]) -> None:
        if "text" in block:
            words.append(block["text"])
        if block.get("alt"):
            words.append(block["alt"])
        for child in block.get("children", []):
            walk(child)
        for item in block.get("items", []):
            for node in item:
                walk(node)

    for block in to_blocks(markdown):
        walk(block)
    return " ".join(words)
