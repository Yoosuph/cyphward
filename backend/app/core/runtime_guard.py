"""Refuse background database work from a non-production process on a remote DB.

The scheduler and scan-recovery loops mutate shared state (they claim scans,
finalise assessments and queue the daily sweep). A developer machine that
inherits a production DATABASE_URL must never run them. They start only when
CYPHWARD_ENV=production, or when every database host is local (loopback or
a Unix socket). An unparseable URL is treated as remote.
"""
import asyncio
import ipaddress
import logging

from psycopg.conninfo import conninfo_to_dict

from backend.app.core.config import CYPHWARD_ENV, DATABASE_URL

logger = logging.getLogger("cyphward.runtime_guard")

REFUSAL_REASON = "non-production process on a non-loopback database"

# Per-process loop status for /health. Values never contain URLs or secrets.
_status: dict[str, str] = {"scheduler": "not started", "recovery": "not started"}
_tasks: dict[str, asyncio.Task] = {}


def set_background_status(name: str, status: str) -> None:
    _tasks.pop(name, None)
    _status[name] = status


def track_background_task(name: str, task: asyncio.Task) -> None:
    _tasks[name] = task
    _status[name] = "running"


def background_status() -> dict[str, str]:
    """'running' only while the loop's task is alive; a dead task reports 'stopped'."""
    result = dict(_status)
    for name, task in _tasks.items():
        if task.done():
            failed = not task.cancelled() and task.exception() is not None
            result[name] = "stopped (error)" if failed else "stopped"
    return result


def _is_local_host(host: str) -> bool:
    host = host.strip().strip("[]").lower()
    if host == "localhost" or host.startswith("/"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def database_is_local(database_url: str) -> bool:
    """True only when every host in the URL is loopback or a Unix socket."""
    try:
        info = conninfo_to_dict(database_url)
    except Exception:
        return False
    hosts = [h for h in (info.get("host") or "").split(",") if h.strip()]
    hosts += [h for h in (info.get("hostaddr") or "").split(",") if h.strip()]
    # No host means libpq's default local socket.
    return all(_is_local_host(host) for host in hosts)


def background_work_allowed(task: str, *, database_url: str | None = None,
                            environment: str | None = None) -> bool:
    url = DATABASE_URL if database_url is None else database_url
    env = (CYPHWARD_ENV if environment is None else environment).strip().lower()
    if env == "production" or not url or database_is_local(url):
        return True
    logger.critical(
        "\n%s\nREFUSING TO START %s: DATABASE_URL points at a non-loopback database "
        "and CYPHWARD_ENV=%r (not 'production').\nThis process will not run "
        "scheduler or scan-recovery work. Use a loopback database for local "
        "development, or set CYPHWARD_ENV=production on a production service.\n%s",
        "!" * 78, task.upper(), env, "!" * 78,
    )
    return False
