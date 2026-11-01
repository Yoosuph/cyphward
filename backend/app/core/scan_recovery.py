"""Durable queue consumption and expired local/Core claim recovery.

Remote recon is exclusively claimed by workers. Local queued jobs survive lost
HTTP/event delivery and are periodically consumed with the same atomic claims.
Expired Core claims can resume without re-running recon. Active claims are never
stolen merely because another API replica starts.
"""

import asyncio
import logging

from backend.app.core.config import SCANNER_MODE
from backend.app.core.database import execute_query
from backend.app.core import scan_execution as execution
from backend.app.services import notifications

logger = logging.getLogger("cyphward.scan_recovery")
INTERRUPTED_MESSAGE = (
    "interrupted: legacy unleased scan cannot be resumed; run a new scan."
)


# Local-mode queue pick. Suspended organisations are left out, as in the worker claim (scan_execution.claim_recon),
# so their queued scans wait without holding the two slots other organisations' scans need (core/suspension.py).
LOCAL_QUEUE_SQL = """SELECT s.id FROM scans s JOIN domains d ON d.id=s.domain_id AND d.org_id=s.org_id
    WHERE d.verification_status='verified' AND (s.status='queued'
    OR (s.status='running' AND s.execution_phase='local' AND s.lease_expires_at < clock_timestamp()))
      AND NOT EXISTS (SELECT 1 FROM organization_suspensions os
                      WHERE os.org_id=s.org_id AND os.status IN ('suspended', 'deleted'))
    ORDER BY s.created_at LIMIT %s"""


def recover_interrupted_scans() -> int:
    if SCANNER_MODE != "local":
        return 0
    rows = execute_query(
        """UPDATE scans SET status = 'failed',error_message=%s,failure_code='interrupted',completed_at=now()
        WHERE claimed_by IS NULL AND status = 'running'
          AND execution_phase IS NULL AND claim_token IS NULL RETURNING id, org_id""",
        (INTERRUPTED_MESSAGE,),
    )
    for row in rows or []:
        if row.get("org_id"):
            notifications.emit("scan_failed", row["org_id"], key=f"scan_failed:{row['id']}",
                               params={"scan_id": row["id"], "code": "interrupted"})
    return len(rows or [])


async def recover_scan_queue(stop: asyncio.Event) -> None:
    from backend.app.workflows.inngest_workflow import (
        execute_scan_pipeline,
        finalize_scan,
    )

    tasks: set[asyncio.Task] = set()

    def finished(task):
        tasks.discard(task)
        if not task.cancelled() and task.exception():
            logger.warning(
                "recovery execution failed: %s", type(task.exception()).__name__
            )

    try:
        while not stop.is_set():
            try:
                slots = max(0, 2 - len(tasks))
                if slots:
                    claims = await asyncio.to_thread(
                        execution.claim_core_recovery, slots
                    )
                    for claim in claims:
                        task = asyncio.create_task(finalize_scan(claim.scan_id, claim))
                        tasks.add(task)
                        task.add_done_callback(finished)
                slots = max(0, 2 - len(tasks))
                if SCANNER_MODE == "local" and slots:
                    rows = await asyncio.to_thread(execute_query, LOCAL_QUEUE_SQL, (slots,))
                    for row in rows or []:
                        task = asyncio.create_task(
                            execute_scan_pipeline(str(row["id"]))
                        )
                        tasks.add(task)
                        task.add_done_callback(finished)
            except Exception:
                logger.exception(
                    "scan queue recovery tick failed; next tick will retry"
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
