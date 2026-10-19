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
    log_level: str = "INFO"


def load_config(require: bool = True) -> BrowserConfig:
    cfg = BrowserConfig(
        core_url=os.getenv("BROWSER_CORE_URL", "").rstrip("/"),
        api_key=os.getenv("BROWSER_API_KEY", ""),
        worker_id=(os.getenv("BROWSER_WORKER_ID", "").strip() or socket.gethostname())[:64],
        poll_interval_seconds=max(5, int(os.getenv("BROWSER_POLL_INTERVAL_SECONDS", "30"))),
        heartbeat_seconds=max(5, min(60, int(os.getenv("BROWSER_HEARTBEAT_SECONDS", "20")))),
        http_timeout_seconds=int(os.getenv("BROWSER_HTTP_TIMEOUT_SECONDS", "30")),
        chromium_path=os.getenv("BROWSER_CHROMIUM_PATH", "").strip(),
        chromium_sandbox=os.getenv("BROWSER_CHROMIUM_SANDBOX", "0").strip() in ("1", "true", "yes"),
        log_level=os.getenv("BROWSER_LOG_LEVEL", "INFO").upper(),
    )
    if require:
        if not cfg.core_url or not cfg.api_key:
            raise SystemExit("BROWSER_CORE_URL and BROWSER_API_KEY are required (fail closed).")
        parts = urlsplit(cfg.core_url)
        local = parts.hostname in ("localhost", "127.0.0.1", "::1")
        if parts.scheme != "https" and not (parts.scheme == "http" and local):
            raise SystemExit("BROWSER_CORE_URL must be https (http is accepted for localhost only).")
    return cfg
