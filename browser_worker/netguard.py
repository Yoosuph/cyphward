"""Egress control for the browser worker: URL checks and a filtering forward proxy.

Request interception alone cannot stop DNS rebinding: the browser resolves a
name itself after the check. So Chromium is pointed at an in-process proxy that
is the only way out. The proxy resolves the host once, refuses the connection
if ANY resolved address is not public (stricter than the scanner, which only
filters to the public ones), and connects to the validated address itself. The
browser never gets to resolve or choose an address.

Loopback is routed through the proxy as well (`--proxy-bypass-list=<-loopback>`),
so `http://127.0.0.1/` and `http://localhost/` are refused like any other
private address. Tests reach their localhost fixtures only by passing an
explicit `EgressPolicy` with an allow-hook; no environment variable does that.
"""
import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit

from backend.app.scanner.ip_guard import is_public_ip

logger = logging.getLogger("cyphward.browser.netguard")

DEFAULT_PORTS = (80, 443)
MAX_URL_LENGTH = 2000
HEAD_LIMIT = 16 * 1024
MAX_CONNECTIONS = 48
IDLE_SECONDS = 30
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")


# Hosts Chromium itself contacts in the background (component updates, extension and account
# services), outside anything the page asked for. No page needs them, so the proxy refuses them:
# they would only leak the worker's address to a third party and add noise to the observation.
BROWSER_INTERNAL_HOSTS = ("clients2.google.com", "update.googleapis.com", "android.clients.google.com",
                          "clients1.google.com", "optimizationguide-pa.googleapis.com", "safebrowsing.googleapis.com")


class Refused(Exception):
    """A URL or address the worker will not touch. `reason` is a short stable code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


Resolver = Callable[[str], Awaitable[List[str]]]


async def system_resolver(host: str) -> List[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, None, type=socket.SOCK_STREAM), timeout=8)
    except (OSError, asyncio.TimeoutError):
        return []
    ips: List[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    return ips


@dataclass(frozen=True)
class EgressPolicy:
    """What the worker may connect to. The default is the production policy."""
    resolver: Resolver = system_resolver
    allowed_ports: Sequence[int] = DEFAULT_PORTS
    allow_ip: Callable[[str], bool] = is_public_ip

    async def resolve(self, host: str) -> List[str]:
        """Addresses to connect to. Raises Refused unless every address passes."""
        host = host.strip().lower().rstrip(".")
        literal = _literal(host)
        ips = [str(literal)] if literal is not None else await self.resolver(host)
        if not ips:
            raise Refused("unresolved", host)
        bad = [ip for ip in ips if not self.allow_ip(ip)]
        if bad:
            raise Refused("refused_address", f"{host} resolves to a non-public address")
        return ips


def _literal(host: str):
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def numeric_host(host: str) -> bool:
    """True for IP literals and for number-like names (decimal, octal or hex IPv4 spellings)."""
    host = host.strip("[]")
    return _literal(host) is not None or re.fullmatch(r"(0x[0-9a-f]+|[0-9]+)", host.rsplit(".", 1)[-1]) is not None


def host_in_scope(host: str, scope: Iterable[str]) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return False
    for suffix in scope:
        s = (suffix or "").strip().lower().rstrip(".")
        if s and (host == s or host.endswith("." + s)):
            return True
    return False


def check_url(url: str, policy: EgressPolicy, *, scope: Sequence[str], main_frame: bool,
              allow_http: bool = True) -> str:
    """Cheap, synchronous checks on any request URL. Returns the lower-cased host.

    The proxy still resolves and validates every connection; this layer refuses what can be
    refused without a lookup, and holds the main frame inside the verified scope.
    """
    if not isinstance(url, str) or len(url) > MAX_URL_LENGTH:
        raise Refused("bad_url", "too long")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise Refused("bad_url", "unparseable")
    if parts.scheme not in ("http", "https") or (parts.scheme == "http" and not allow_http):
        raise Refused("bad_scheme", parts.scheme or "none")
    if parts.username is not None or parts.password is not None:
        raise Refused("bad_url", "credentials in url")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise Refused("bad_url", "no host")
    effective = port or (443 if parts.scheme == "https" else 80)
    if effective not in policy.allowed_ports:
        raise Refused("bad_port", str(effective))
    literal = _literal(host)
    if literal is not None:
        if not policy.allow_ip(str(literal)):
            raise Refused("refused_address", "literal address is not public")
    elif not _HOST_RE.match(host):
        raise Refused("bad_url", "unsupported host form")
    elif numeric_host(host):
        # Decimal, octal and hex spellings of an address: never a registered domain name.
        raise Refused("refused_address", "numeric host")
    if main_frame and not host_in_scope(host, scope):
        raise Refused("off_scope_redirect", host)
    return host


@dataclass
class Budget:
    """Shared, mutable limits for one job; the proxy and the route handler both charge it."""
    max_bytes: int
    bytes_used: int = 0
    bytes_capped: bool = False

    def charge(self, n: int) -> bool:
        self.bytes_used += n
        if self.bytes_used > self.max_bytes:
            self.bytes_capped = True
        return not self.bytes_capped


@dataclass
class ConnectProxy:
    """Minimal HTTP/1.1 forward proxy: CONNECT tunnels and absolute-URI plain HTTP."""
    policy: EgressPolicy
    budget: Budget
    refused: List[Refused] = field(default_factory=list)
    connected: List[str] = field(default_factory=list)
    _server: Optional[asyncio.AbstractServer] = None
    _tasks: set = field(default_factory=set)
    port: int = 0

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0, limit=HEAD_LIMIT)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._server is not None:
            await self._server.wait_closed()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            if len(self._tasks) > MAX_CONNECTIONS:
                await self._deny(writer, Refused("too_many_connections"))
                return
            await self._serve(reader, writer)
        except (asyncio.CancelledError, ConnectionError, asyncio.IncompleteReadError, asyncio.TimeoutError, OSError):
            pass
        finally:
            self._tasks.discard(task)
            writer.close()

    async def _deny(self, writer: asyncio.StreamWriter, refusal: Refused) -> None:
        self.refused.append(refusal)
        try:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n"
                         b"X-Cyphward-Refused: " + refusal.reason.encode("ascii", "replace") + b"\r\n\r\n")
            await writer.drain()
        except (ConnectionError, OSError):
            pass

    async def _serve(self, reader, writer) -> None:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        if len(head) > HEAD_LIMIT:
            return await self._deny(writer, Refused("bad_request", "head too large"))
        lines = head.split(b"\r\n")
        try:
            method, target, version = lines[0].decode("ascii").split(" ")
        except (UnicodeDecodeError, ValueError):
            return await self._deny(writer, Refused("bad_request", "request line"))
        try:
            if method.upper() == "CONNECT":
                host, _, port_text = target.rpartition(":")
                if not host or not port_text.isdigit():
                    raise Refused("bad_request", "connect target")
                host, port, leftover, rewritten = host.strip("[]"), int(port_text), b"", None
                tls = True
            else:
                parts = urlsplit(target)
                if parts.scheme != "http" or not parts.hostname:
                    raise Refused("bad_scheme", "proxy accepts http:// or CONNECT only")
                host, port, tls = parts.hostname, parts.port or 80, False
                path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                kept = [ln for ln in lines[1:-2] if not ln.lower().startswith((b"proxy-", b"connection:", b"keep-alive:"))]
                rewritten = b"\r\n".join([f"{method} {path} {version}".encode("ascii")] + kept
                                         + [b"Connection: close"]) + b"\r\n\r\n"
            if port not in self.policy.allowed_ports:
                raise Refused("bad_port", str(port))
            if host.lower().rstrip(".") in BROWSER_INTERNAL_HOSTS:
                raise Refused("browser_internal", host)
            ips = await self.policy.resolve(host)
        except Refused as refusal:
            return await self._deny(writer, refusal)

        upstream = await self._connect(ips, port)
        if upstream is None:
            return await self._deny(writer, Refused("connect_failed", host))
        up_reader, up_writer = upstream
        self.connected.append(f"{host}:{port}")
        try:
            if tls:
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
            else:
                up_writer.write(rewritten)
                await up_writer.drain()
            await self._pipe(reader, writer, up_reader, up_writer)
        finally:
            up_writer.close()

    async def _connect(self, ips: List[str], port: int):
        # Connect to the address that was validated. The name is never resolved again.
        for ip in ips:
            try:
                return await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=10)
            except (OSError, asyncio.TimeoutError):
                continue
        return None

    async def _pipe(self, c_reader, c_writer, u_reader, u_writer) -> None:
        async def pump(src, dst, count: bool) -> None:
            while True:
                data = await asyncio.wait_for(src.read(65536), timeout=IDLE_SECONDS)
                if not data:
                    return
                if count and not self.budget.charge(len(data)):
                    return  # byte cap reached: cut the connection
                dst.write(data)
                await dst.drain()

        tasks = [asyncio.create_task(pump(c_reader, u_writer, False)), asyncio.create_task(pump(u_reader, c_writer, True))]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
