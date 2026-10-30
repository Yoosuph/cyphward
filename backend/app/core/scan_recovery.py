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

logger = logging.getLogger("cyphward.scan_recovery")
INTERRUPTED_MESSAGE = (
    "interrupted: legacy unleased scan cannot be resumed; run a new scan."
)


def recover_interrupted_scans() -> int:
    if SCANNER_MODE != "local":
        return 0
    rows = execute_query(
        """UPDATE scans SET status = 'failed',error_message=%s,failure_code='interrupted',completed_at=now()
        WHERE claimed_by IS NULL AND status = 'running'
          AND execution_phase IS NULL AND claim_token IS NULL RETURNING id""",
        (INTERRUPTED_MESSAGE,),
    )
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
                    rows = await asyncio.to_thread(
                        execute_query,
                        """SELECT s.id FROM scans s JOIN domains d ON d.id=s.domain_id AND d.org_id=s.org_id
                        WHERE d.verification_status='verified' AND (s.status='queued'
                        OR (s.status='running' AND s.execution_phase='local' AND s.lease_expires_at < clock_timestamp()))
                        ORDER BY s.created_at LIMIT %s""",
                        (slots,),
                    )
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
