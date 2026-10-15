"""Monotonic per-attempt recon work budgets, shared by both execution paths.

Queue time and Core finalisation are outside this budget. Control-plane writes
consume elapsed time but are not interrupted by it; process cleanup can extend
observed duration. Native DNS threads cannot be forcibly killed.
"""
import asyncio
import time
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

_stage_deadline = ContextVar("recon_stage_deadline", default=None)
_thread_deadline = ContextVar("recon_thread_deadline", default=None)


class BudgetExceeded(TimeoutError):
    pass


def ensure_stage_budget():
    """Check again at connection/process boundaries, including copied threads."""
    deadline = _thread_deadline.get()
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BudgetExceeded("recon_stage_deadline")
    return remaining


class ReconBudget:
    def __init__(self, total_seconds, stage_seconds, *, clock=time.monotonic):
        if total_seconds <= 0 or stage_seconds <= 0:
            raise ValueError("recon budgets must be positive")
        self.clock = clock
        self.end = clock() + total_seconds
        self.total_seconds = total_seconds
        self.stage_seconds = stage_seconds
        self.started = datetime.now(timezone.utc)

    def remaining(self):
        return max(0, self.end - self.clock())

    def payload(self):
        return {"version": 1, "phase": "recon", "total_seconds": self.total_seconds,
                "stage_seconds": self.stage_seconds, "started_at": self.started.isoformat(),
                "deadline_at": (self.started + timedelta(seconds=self.total_seconds)).isoformat(),
                "remaining_seconds": round(self.remaining(), 3)}

    async def run(self, factory):
        if self.remaining() <= 0:
            raise BudgetExceeded("recon_budget_exhausted")
        # Use the event loop's monotonic time for asyncio.wait; the injectable
        # clock is only for deterministic budget allocation tests.
        deadline = asyncio.get_running_loop().time() + min(self.stage_seconds, self.remaining())
        token = _stage_deadline.set(deadline)
        thread_token = _thread_deadline.set(time.monotonic() + min(self.stage_seconds, self.remaining()))
        try:
            # Batches use the exact deadline and retain completed results.
            # A two-second coordination allowance lets cancellation/reaping
            # finish before this guard stops an uncooperative stage adapter.
            guard = asyncio.timeout(min(self.stage_seconds, self.remaining()) + 2)
            try:
                async with guard:
                    return await factory()
            except TimeoutError as error:
                if guard.expired():
                    raise BudgetExceeded("recon_stage_deadline") from error
                raise
        finally:
            _stage_deadline.reset(token)
            _thread_deadline.reset(thread_token)


async def gather_with_deadline(awaitables):
    """Preserve completed results in input order and reap cancelled tasks."""
    awaitables = list(awaitables)
    deadline = _stage_deadline.get()
    if deadline is None:
        return await asyncio.gather(*awaitables, return_exceptions=True)
    remaining = max(0, deadline - asyncio.get_running_loop().time())
    if remaining <= 0:
        for awaitable in awaitables:
            if asyncio.isfuture(awaitable):
                awaitable.cancel()
            else:
                awaitable.close()
        return [BudgetExceeded("recon_stage_deadline") for _ in awaitables]
    tasks = [asyncio.ensure_future(awaitable) for awaitable in awaitables]
    if not tasks:
        return []
    try:
        done, pending = await asyncio.wait(tasks, timeout=remaining)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return [BudgetExceeded("recon_stage_deadline") if task in pending else
                task.exception() if task.exception() is not None else task.result()
                for task in tasks]
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
