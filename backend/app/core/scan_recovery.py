"""Startup recovery for scans orphaned by a process restart.

local mode runs scan pipelines inside this API process (Inngest-event
fallback via FastAPI BackgroundTasks, or inline dispatch) and those rows
never get `claimed_by` / `lease_expires_at`. If the process dies mid-run the
row stays queued/running forever — nothing external will ever pick it up.
On startup we fail exactly those rows so the UI shows an honest terminal
state and the user can relaunch.

remote mode is untouched: queued rows legitimately wait for the worker
(claimed_by NULL is the waiting state) and running rows carry a worker
lease whose expiry / core-recovery path in api/scanner_jobs already owns
resumption. The claimed_by IS NULL filter keeps remote-leased work safe
even if this ever runs there.

Single-replica assumption: local mode assumes one API process. Run
SCANNER_MODE=remote for replicas — that is also the mode with lease-based
recovery.
"""
import logging

from backend.app.core.config import SCANNER_MODE
from backend.app.core.database import execute_query

logger = logging.getLogger("cyphward.scan_recovery")

INTERRUPTED_MESSAGE = (
    "interrupted: the service restarted before this scan finished; run a new scan."
)


def recover_interrupted_scans() -> int:
    """Fail scan rows this process can no longer continue. Returns count."""
    if SCANNER_MODE != "local":
        return 0
    rows = execute_query(
        """
        UPDATE scans
           SET status = 'failed',
               error_message = %s,
               completed_at = now()
         WHERE claimed_by IS NULL
           AND status IN ('queued', 'running')
        RETURNING id
        """,
        (INTERRUPTED_MESSAGE,),
    )
    count = len(rows or [])
    if count:
        logger.warning("failed %d scan(s) interrupted by restart", count)
    return count
