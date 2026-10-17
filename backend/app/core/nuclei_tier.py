"""Which Nuclei tier a claimed scan runs.

A domain gets a weekly (full safe set) run when no weekly run has been attempted for it in the last
seven days; every other scan is a daily (critical + high) run. "Attempted" means the worker recorded a
weekly Nuclei observation, so a run that crashed before reporting is tried again, while a run that
reported partial coverage is not retried until the next week.

A weekly run needs more time than a daily one, so its job carries larger stage and recon timeouts.
"""
from typing import Dict, Optional, Tuple

from backend.app.core.database import execute_one
from backend.app.scanner.nuclei_runner import NUCLEI_TIERS

WEEKLY_INTERVAL_DAYS = 7
# Time for everything else in recon (discovery, DNS, HTTP, ports, TLS, privacy) on top of the Nuclei budget.
RECON_ALLOWANCE_SECONDS = 900


def choose_tier(org_id: str, domain_id: str) -> str:
    row = execute_one(
        "SELECT 1 AS found FROM scan_results sr JOIN scans s ON s.id = sr.scan_id "
        "WHERE s.org_id = %s AND s.domain_id = %s AND sr.stage = 'nuclei' "
        "AND sr.created_at > now() - make_interval(days => %s) "
        "AND sr.raw_data->'tool_coverage'->>'tier' = 'weekly' LIMIT 1",
        (org_id, domain_id, WEEKLY_INTERVAL_DAYS),
    )
    return "daily" if row else "weekly"


def timeouts_for(tier: str, stage_seconds: int, recon_seconds: int) -> Tuple[int, int]:
    """(stage, recon) timeouts for a job of this tier. A daily job keeps the configured values."""
    if tier != "weekly":
        return stage_seconds, recon_seconds
    budget = NUCLEI_TIERS["weekly"]["budget_seconds"]
    return max(stage_seconds, budget), max(recon_seconds, budget + RECON_ALLOWANCE_SECONDS)
