"""The one scan-cancel transition, shared by the customer endpoint and the
owner console.

Conditional: only an active scan may become cancelled, so a completion racing
the request is never overwritten. Clearing the lease and bumping the claim
generation also fences any worker that already holds the job (its next
progress/complete/fail call gets 409 and aborts).
"""

CANCEL_ACTIVE_SCAN_SQL = """
        UPDATE scans
        SET status = 'cancelled', completed_at = now(),
            claimed_by = NULL, lease_expires_at = NULL, claim_token = NULL,
            execution_phase = NULL, claim_generation = claim_generation + 1
        WHERE id = %s AND org_id = %s AND status IN ('queued', 'running')
        RETURNING id
    """
