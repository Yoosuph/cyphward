"""Security response headers for the API host.

Pure ASGI (safe for streamed responses). Headers a route already set are
never overwritten. JSON endpoints get a locked-down CSP; the interactive docs
pages get one that allows the Swagger/ReDoc assets they load.
"""
from typing import List, Tuple

HSTS = "max-age=63072000; includeSubDomains"
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://fastapi.tiangolo.com "
            "https://cdn.redoc.ly; worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'")
DOCS_PATHS = ("/docs", "/redoc", "/api/v1/docs")


def _headers_for(path: str) -> List[Tuple[bytes, bytes]]:
    csp = DOCS_CSP if path in DOCS_PATHS or path.startswith("/docs/") else API_CSP
    return [
        (b"strict-transport-security", HSTS.encode()),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"content-security-policy", csp.encode()),
    ]


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        extra = _headers_for(scope.get("path") or "")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {name.lower() for name, _ in message.get("headers") or []}
                message = {**message, "headers": list(message.get("headers") or [])
                           + [(n, v) for n, v in extra if n not in existing]}
            await send(message)

        return await self.app(scope, receive, send_with_headers)
