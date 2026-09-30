"""
Scanner worker configuration — environment-driven (spec §29).
Required: SCANNER_CORE_URL, SCANNER_API_KEY.
"""
import os
import socket
from dataclasses import dataclass


def _load_dotenv_if_present() -> None:
    """Optional .env support for local development; systemd uses EnvironmentFile."""
    try:
        from dotenv import load_dotenv
        if os.path.exists(".env"):
            load_dotenv(".env")
    except ImportError:
        pass


@dataclass(frozen=True)
class WorkerConfig:
    core_url: str
    api_key: str
    scanner_id: str
    poll_interval_seconds: int = 30
    # Lease heartbeat cadence — must be well below Core's SCANNER_LEASE_SECONDS.
    heartbeat_seconds: int = 300
    http_timeout_seconds: int = 30
    # Bounded concurrency for bulk probe stages (FD/memory safety on small VMs).
    http_probe_concurrency: int = 25
    log_level: str = "INFO"


def load_config(require: bool = True) -> WorkerConfig:
    _load_dotenv_if_present()

    cfg = WorkerConfig(
        core_url=os.getenv("SCANNER_CORE_URL", "").rstrip("/"),
        api_key=os.getenv("SCANNER_API_KEY", ""),
        scanner_id=os.getenv("SCANNER_ID", "").strip() or socket.gethostname(),
        poll_interval_seconds=int(os.getenv("SCANNER_POLL_INTERVAL_SECONDS", "30")),
        heartbeat_seconds=int(os.getenv("SCANNER_HEARTBEAT_SECONDS", "300")),
        http_timeout_seconds=int(os.getenv("SCANNER_HTTP_TIMEOUT_SECONDS", "30")),
        http_probe_concurrency=int(os.getenv("SCANNER_HTTP_PROBE_CONCURRENCY", "25")),
        log_level=os.getenv("SCANNER_LOG_LEVEL", "INFO").upper(),
    )

    if require and (not cfg.core_url or not cfg.api_key):
        raise SystemExit(
            "SCANNER_CORE_URL and SCANNER_API_KEY are required "
            "(fail closed — the worker never runs unauthenticated)."
        )
    return cfg
