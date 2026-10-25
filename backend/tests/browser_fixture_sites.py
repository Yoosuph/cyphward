"""Localhost fixture sites for the browser worker tests. Nothing here touches the network.

One threaded HTTP server answers for many pretend host names (the browser's requests carry the
name in Host, because they arrive through the worker's proxy), so each scenario gets its own
verified host. A test resolver maps those names to 127.0.0.1; names meant to be refused map to
private addresses and must never be connected to.
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List

from backend.app.scanner.ip_guard import is_public_ip
from browser_worker.netguard import EgressPolicy

BANNER_BOTH = """<html><body><h1>Shop</h1>
<div id="onetrust-banner-sdk" style="position:fixed;bottom:0;left:0;right:0;background:#eee;padding:12px">
We use cookies.
<button style="width:140px;height:40px">Accept all</button>
<button style="width:140px;height:40px">Reject all</button>
</div></body></html>"""

BANNER_ACCEPT_ONLY = """<html><body><h1>Shop</h1>
<div role="dialog" style="position:fixed;bottom:0;left:0;right:0;background:#eee;padding:12px">
This site uses cookies for analytics.
<button style="width:140px;height:40px">Accept all</button>
<a href="/settings">Manage preferences</a>
</div></body></html>"""

BANNER_SMALL_REJECT = """<html><body><h1>Shop</h1>
<div role="dialog" style="position:fixed;bottom:0;left:0;right:0;background:#eee;padding:12px">
We value your privacy: cookie choices.
<button style="width:160px;height:44px">Accept all</button>
<a href="/no" style="font-size:9px">Reject</a>
</div></body></html>"""

CLEAN = "<html><body><h1>Plain page</h1><p>No scripts, no cookies.</p></body></html>"

COOKIES = """<html><body><h1>News</h1>
<script>document.cookie = "_fbp=fb.1.2.3; path=/; max-age=7776000";</script>
<img src="http://tracker.test:%(port)s/pixel.gif"></body></html>"""


def many_images(port: int, count: int) -> str:
    return "<html><body>" + "".join(f'<img src="/i/{n}.gif">' for n in range(count)) + "</body></html>"


class FixtureServer:
    def __init__(self):
        self.seen_hosts: List[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, status, body=b"", headers=()):
                self.send_response(status)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def do_GET(self):
                host = (self.headers.get("Host") or "").split(":")[0]
                outer.seen_hosts.append(host)
                path = self.path.split("?")[0]
                port = self.server.server_address[1]
                html = [("Content-Type", "text/html; charset=utf-8")]
                if path.startswith("/i/") or path == "/pixel.gif":
                    return self._send(200, b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
                                           b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;", [("Content-Type", "image/gif")])
                if host == "cookies.test":
                    return self._send(200, (COOKIES % {"port": port}).encode(), html + [
                        ("Set-Cookie", "_ga=GA1.2.1.2; Path=/; Max-Age=63072000"),
                        ("Set-Cookie", "sid=abc123; Path=/; HttpOnly; SameSite=Lax")])
                if host == "clean.test":
                    return self._send(200, CLEAN.encode(), html)
                if host == "banner-both.test":
                    return self._send(200, BANNER_BOTH.encode(), html)
                if host == "banner-accept-only.test":
                    return self._send(200, BANNER_ACCEPT_ONLY.encode(), html)
                if host == "banner-small-reject.test":
                    return self._send(200, BANNER_SMALL_REJECT.encode(), html)
                if host == "redirect-metadata.test":
                    return self._send(302, b"", [("Location", "http://169.254.169.254/latest/meta-data/")])
                if host == "redirect-private.test":
                    return self._send(302, b"", [("Location", "http://10.0.0.5/admin")])
                if host == "redirect-offscope.test":
                    return self._send(302, b"", [("Location", "http://other.test:%d/" % port)])
                if host == "redirect-hostname-private.test":
                    return self._send(302, b"", [("Location", "http://private.test:%d/" % port)])
                if host == "redirect-inscope.test":
                    return self._send(302, b"", [("Location", "http://www.redirect-inscope.test:%d/landing" % port)])
                if host == "www.redirect-inscope.test":
                    return self._send(200, CLEAN.encode(), html)
                if host == "subresource-private.test":
                    return self._send(200, f'<html><body><img src="http://private.test:{port}/x.gif"></body></html>'.encode(), html)
                if host == "slow.test":
                    time.sleep(12)
                    return self._send(200, CLEAN.encode(), html)
                if host == "images.test":
                    return self._send(200, many_images(port, 60).encode(), html)
                if host == "huge.test":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    chunk = (b"<p>" + b"x" * 8000 + b"</p>")
                    try:
                        for _ in range(8000):  # ~64 MB if nobody stops us
                            self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                if host == "popup.test":
                    return self._send(200, (f'<html><body><script>window.open("http://other.test:{port}/", "_blank");'
                                            f'document.title="popup";</script><a target="_blank" href="/x">x</a></body></html>').encode(), html)
                if host == "script-redirect.test":
                    return self._send(200, (f'<html><body>hello<script>setTimeout(function(){{ location = "http://other.test:{port}/"; }}, 200);'
                                            f'</script></body></html>').encode(), html)
                if host == "download.test":
                    return self._send(200, b"binary", [("Content-Type", "application/octet-stream"),
                                                       ("Content-Disposition", "attachment; filename=x.bin")])
                return self._send(404, b"not found", html)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def url(self, host: str, path: str = "/") -> str:
        return f"http://{host}:{self.port}{path}"

    def policy(self) -> EgressPolicy:
        names: Dict[str, List[str]] = {
            "private.test": ["10.0.0.9"], "rebind.test": ["8.8.8.8", "10.0.0.9"], "public.test": ["8.8.8.8"],
        }

        async def resolver(host: str) -> List[str]:
            if host in names:
                return names[host]
            if host.endswith(".test"):
                return ["127.0.0.1"]
            return []

        class AnyPort:
            def __contains__(self, port):
                return True

        # The test policy's only widening: the fixture server on loopback may be reached. Real
        # loopback and every other private range stay refused, which is what the tests prove.
        return EgressPolicy(resolver=resolver, allowed_ports=AnyPort(),
                            allow_ip=lambda ip: ip == "127.0.0.1" or is_public_ip(ip))
