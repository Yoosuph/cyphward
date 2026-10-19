"""Self-check of the image: python -m browser_worker.smoke

Starts a tiny web server on loopback inside the container, visits it once with the real browser, and
prints what the browser observed. It proves Chromium, the proxy and the report shape work with the
container's hardening (read-only root, dropped capabilities, memory limit). It never contacts Core and
never touches the network. The loopback allowance exists only in this module, for this one port.
"""
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from browser_worker.config import load_config
from browser_worker.netguard import EgressPolicy
from browser_worker.observer import Limits, observe
from shared.browser_contracts import ConsentObservation

PAGE = b"""<html><body><h1>Smoke</h1>
<div role="dialog" style="position:fixed;bottom:0;left:0;right:0;background:#eee;padding:12px">We use cookies.
<button style="width:140px;height:40px">Accept all</button><button style="width:140px;height:40px">Reject all</button></div>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Set-Cookie", "smoke=1; Path=/")
        self.send_header("Content-Length", str(len(PAGE)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(PAGE)


def main() -> int:
    cfg = load_config(require=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    async def resolver(host):
        return ["127.0.0.1"]

    policy = EgressPolicy(resolver=resolver, allowed_ports=[port], allow_ip=lambda ip: ip == "127.0.0.1")
    try:
        result = asyncio.run(observe(f"http://smoke.test:{port}/", ["smoke.test"], policy,
                                     limits=Limits(page_timeout_seconds=20, job_timeout_seconds=40, settle_seconds=0.5),
                                     chromium_path=cfg.chromium_path or None, sandbox=cfg.chromium_sandbox, allow_http=True))
        observation = ConsentObservation.model_validate(result)
    finally:
        server.shutdown()
    ok = (len(observation.cookies) == 1 and observation.banner.detected and observation.banner.reject_control == "same_level")
    print(json.dumps({"ok": ok, "browser": observation.browser_version, "cookies": len(observation.cookies),
                      "banner": observation.banner.model_dump()}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
