"""Lesson video: an allow-listed provider URL in, a privacy-friendly embed URL out (built from the parsed id).

Only these are accepted. The embed URL is rebuilt from the provider's id, never passed through, so no query string,
fragment or other host a writer pasted can reach the learner's browser. The learner page shows it in a sandboxed
iframe (frontend/src/academy/VideoEmbed.tsx) and the academy host's Content-Security-Policy allows only these hosts
in frame-src (vercel.json).

  YouTube   youtube.com/watch?v=ID, youtu.be/ID, youtube.com/embed/ID, youtube.com/shorts/ID,
            youtube-nocookie.com/embed/ID                    -> https://www.youtube-nocookie.com/embed/ID
  Vimeo     vimeo.com/123, vimeo.com/123/HASH, player.vimeo.com/video/123[?h=HASH]
                                                             -> https://player.vimeo.com/video/123?dnt=1[&h=HASH]
  Mux       player.mux.com/PLAYBACK_ID, stream.mux.com/PLAYBACK_ID[.m3u8]
                                                             -> https://player.mux.com/PLAYBACK_ID
  Bunny     iframe.mediadelivery.net/embed/LIB/VIDEO, player.mediadelivery.net/embed/LIB/VIDEO
                                                             -> https://iframe.mediadelivery.net/embed/LIB/VIDEO
"""
import re
from typing import Optional
from urllib.parse import parse_qs, urlsplit

EMBED_HOSTS = ("www.youtube-nocookie.com", "player.vimeo.com", "player.mux.com", "iframe.mediadelivery.net")
PROVIDERS = ("YouTube", "Vimeo", "Mux", "Bunny Stream")
REFUSED = ("Use a video link from YouTube, Vimeo, Mux or Bunny Stream. Other video sites cannot be embedded.")

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_DIGITS = re.compile(r"^[0-9]{1,15}$")
_HASH = re.compile(r"^[0-9a-f]{6,40}$")
_MUX_ID = re.compile(r"^[A-Za-z0-9]{10,80}$")
_BUNNY_VIDEO = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def embed_url(raw: Optional[str]) -> Optional[str]:
    """The embed URL for an allow-listed video link, None for an empty value. Raises ValueError otherwise."""
    value = (raw or "").strip()
    if not value:
        return None
    if len(value) > 500 or any(c.isspace() for c in value):
        raise ValueError(REFUSED)
    parts = urlsplit(value if "://" in value else f"https://{value}")
    if parts.scheme not in ("http", "https") or parts.username or parts.password or parts.port:
        raise ValueError(REFUSED)
    host = (parts.hostname or "").lower()
    segs = [s for s in parts.path.split("/") if s]
    query = parse_qs(parts.query)

    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com",
                "www.youtube-nocookie.com"):
        vid = None
        if host == "youtu.be" and segs:
            vid = segs[0]
        elif segs[:1] == ["watch"] or (not segs and "v" in query):
            vid = (query.get("v") or [None])[0]
        elif len(segs) >= 2 and segs[0] in ("embed", "shorts", "live"):
            vid = segs[1]
        if vid and _YT_ID.match(vid):
            return f"https://www.youtube-nocookie.com/embed/{vid}"
        raise ValueError(REFUSED)

    if host in ("vimeo.com", "www.vimeo.com", "player.vimeo.com"):
        if host == "player.vimeo.com":
            vid = segs[1] if len(segs) >= 2 and segs[0] == "video" else None
            secret = (query.get("h") or [None])[0]
        else:
            vid = segs[0] if segs else None
            secret = segs[1] if len(segs) >= 2 else None
        if vid and _DIGITS.match(vid) and (secret is None or _HASH.match(secret)):
            return f"https://player.vimeo.com/video/{vid}?dnt=1" + (f"&h={secret}" if secret else "")
        raise ValueError(REFUSED)

    if host in ("player.mux.com", "stream.mux.com"):
        pid = segs[0].removesuffix(".m3u8") if len(segs) == 1 else None
        if pid and _MUX_ID.match(pid):
            return f"https://player.mux.com/{pid}"
        raise ValueError(REFUSED)

    if host in ("iframe.mediadelivery.net", "player.mediadelivery.net"):
        if len(segs) == 3 and segs[0] in ("embed", "play") and _DIGITS.match(segs[1]) and _BUNNY_VIDEO.match(segs[2].lower()):
            return f"https://iframe.mediadelivery.net/embed/{segs[1]}/{segs[2].lower()}"
        raise ValueError(REFUSED)

    raise ValueError(REFUSED)


def is_embed_url(value: Optional[str]) -> bool:
    """True when a stored value is one this module produced (checked again on every read)."""
    if not value:
        return False
    try:
        return embed_url(value) == value
    except ValueError:
        return False
