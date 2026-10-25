"""Browser worker configuration, environment-driven. Names only here; values live in the VM's env file."""
import os
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class BrowserConfig:
    core_url: str
    api_key: str
    worker_id: str
    poll_interval_seconds: int = 30
    heartbeat_seconds: int = 20
    http_timeout_seconds: int = 30
    chromium_path: str = ""
    chromium_sandbox: bool = False
    no_sandbox_acknowledged: bool = False
    log_level: str = "INFO"


def read_api_key(require: bool = True) -> str:
    """The worker's key, from the safest source available, in this order:

    1. stdin (BROWSER_API_KEY_STDIN=1): one line read at start-up, then stdin is closed. The key then
       exists only in this process's memory: not in any environment, not in any file in the container.
    2. a file (BROWSER_API_KEY_FILE): a mounted secret. Readable by this user, so weaker than stdin.
    3. the environment (BROWSER_API_KEY): simplest, and the one a same-user browser exploit could read from
       /proc; allowed, but the runbook says to avoid it.
    Whatever the source, the variable is removed from this process's environment before anything else starts.
    """
    if os.environ.get("BROWSER_API_KEY_STDIN", "0").strip() == "1":
        import sys
        line = sys.stdin.readline().strip() if require else ""
        try:
            sys.stdin.close()
        except OSError:
            pass
        return line
    path = os.environ.get("BROWSER_API_KEY_FILE", "").strip()
    if path:
        try:
            with open(path, encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            raise SystemExit(f"BROWSER_API_KEY_FILE ({path}) cannot be read (fail closed).")
    return os.environ.pop("BROWSER_API_KEY", "")


def load_config(require: bool = True) -> BrowserConfig:
    cfg = BrowserConfig(
        core_url=os.getenv("BROWSER_CORE_URL", "").rstrip("/"),
        api_key=read_api_key(require),
        worker_id=(os.getenv("BROWSER_WORKER_ID", "").strip() or socket.gethostname())[:64],
        poll_interval_seconds=max(5, int(os.getenv("BROWSER_POLL_INTERVAL_SECONDS", "30"))),
        heartbeat_seconds=max(5, min(60, int(os.getenv("BROWSER_HEARTBEAT_SECONDS", "20")))),
        http_timeout_seconds=int(os.getenv("BROWSER_HTTP_TIMEOUT_SECONDS", "30")),
        chromium_path=os.getenv("BROWSER_CHROMIUM_PATH", "").strip(),
        chromium_sandbox=os.getenv("BROWSER_CHROMIUM_SANDBOX", "1").strip() in ("1", "true", "yes"),
        no_sandbox_acknowledged=os.getenv("BROWSER_ACK_NO_SANDBOX_EGRESS_FIREWALL", "0").strip() == "1",
        log_level=os.getenv("BROWSER_LOG_LEVEL", "INFO").upper(),
    )
    if require:
        if not cfg.core_url or not cfg.api_key:
            raise SystemExit("BROWSER_CORE_URL and a key (BROWSER_API_KEY_STDIN=1, BROWSER_API_KEY_FILE or "
                             "BROWSER_API_KEY) are required (fail closed).")
        parts = urlsplit(cfg.core_url)
        local = parts.hostname in ("localhost", "127.0.0.1", "::1")
        if parts.scheme != "https" and not (parts.scheme == "http" and local):
            raise SystemExit("BROWSER_CORE_URL must be https (http is accepted for localhost only).")
        if not cfg.chromium_sandbox and not cfg.no_sandbox_acknowledged:
            # Without Chromium's sandbox a renderer exploit runs as the worker's user and could read the
            # worker's key. Starting that way needs an explicit statement that the mandatory egress
            # firewall from the runbook is in place; there is no silent default.
            raise SystemExit("Chromium's sandbox is off. Either set BROWSER_CHROMIUM_SANDBOX=1, or confirm the "
                             "mandatory egress firewall from docs/runbooks/browser-worker.md is in place with "
                             "BROWSER_ACK_NO_SANDBOX_EGRESS_FIREWALL=1.")
    return cfg
