"""Execution authority propagated to all database helpers in a pipeline task.

No database import here: the database layer can enforce the fence for indirect
notification/audit helpers without a circular dependency. A context is authority
for one attempt, never a substitute for the transactional row check below.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import secrets


class ClaimLost(RuntimeError):
    """The attempt is expired, cancelled, terminal or superseded."""


@dataclass(frozen=True)
class ExecutionClaim:
    scan_id: str
    owner: str
    generation: int
    token: str = field(repr=False)
    observation_generation: int
    phase: str


current_claim: ContextVar[ExecutionClaim | None] = ContextVar(
    "scan_execution_claim", default=None
)


@contextmanager
def execution_scope(claim: ExecutionClaim):
    if not claim.token or claim.generation < 1:
        raise ClaimLost("Missing execution authority")
    reset = current_claim.set(claim)
    try:
        yield claim
    finally:
        current_claim.reset(reset)


def require_execution(scan_id: str) -> ExecutionClaim:
    claim = current_claim.get()
    if claim is None or claim.scan_id != str(scan_id):
        raise ClaimLost("Explicit execution authority is required")
    return claim


def lock_claim(cur, claim: ExecutionClaim) -> dict:
    """Validate after acquiring the lock, using the database clock after waits."""
    cur.execute("SET LOCAL lock_timeout = '5s'")
    cur.execute("SET LOCAL statement_timeout = '15s'")
    cur.execute(
        """SELECT id, org_id, status, claimed_by, claim_generation, claim_token,
                  observation_generation, execution_phase, lease_expires_at, stage_progress
           FROM scans WHERE id = %s FOR UPDATE""",
        (claim.scan_id,),
    )
    row = cur.fetchone()
    cur.execute("SELECT clock_timestamp() AS claim_now")
    now = cur.fetchone()["claim_now"]
    if (
        not row
        or row["status"] != "running"
        or row["claimed_by"] != claim.owner
        or row["claim_generation"] != claim.generation
        or row["execution_phase"] != claim.phase
        or row["observation_generation"] != claim.observation_generation
        or not secrets.compare_digest(
            str(row["claim_token"] or "").encode(), claim.token.encode()
        )
        or not row["lease_expires_at"]
        or row["lease_expires_at"] <= now
    ):
        raise ClaimLost("Execution claim is no longer current")
    return row
