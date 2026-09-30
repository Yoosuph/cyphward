"""
Cyphward scanner ↔ core shared contracts (spec §21).

Single source of truth for the job/observation API between FastAPI Core and the
Azure scanner worker. Pydantic-only — no FastAPI, no DB, safe to import from
either side. Do NOT duplicate these models elsewhere.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Stage model — one ordered list drives progress tracking on both sides.
# ---------------------------------------------------------------------------
STAGE_DISCOVERY = "discovery"
STAGE_DNS = "dns"
STAGE_HTTP = "http"
STAGE_PORTS = "ports"
STAGE_TLS = "tls"
STAGE_NUCLEI = "nuclei"
STAGE_SECURITY_CHECKS = "security_checks"
STAGE_NORMALIZATION = "normalization"
STAGE_SCORING = "scoring"
STAGE_AI_ANALYSIS = "ai_analysis"

# Recon stages: executed by the scanner worker (or local fallback).
RECON_STAGES = [
    STAGE_DISCOVERY,
    STAGE_DNS,
    STAGE_HTTP,
    STAGE_PORTS,
    STAGE_TLS,
    STAGE_NUCLEI,
]

# Core stages: executed by FastAPI after observations arrive.
CORE_STAGES = [
    STAGE_SECURITY_CHECKS,
    STAGE_NORMALIZATION,
    STAGE_SCORING,
    STAGE_AI_ANALYSIS,
]

ALL_STAGES = RECON_STAGES + CORE_STAGES

# Stages whose raw payloads may be submitted via the observations endpoint.
OBSERVATION_STAGES = set(RECON_STAGES)

VALID_PROGRESS_STATUSES = {"queued", "pending", "running", "completed", "failed", "skipped"}


def empty_stage_progress() -> Dict[str, Dict[str, Any]]:
    """Initial stage_progress template (queued) for a new scan row."""
    return {
        STAGE_DISCOVERY: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_DNS: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_HTTP: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_PORTS: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_TLS: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_NUCLEI: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_SECURITY_CHECKS: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_NORMALIZATION: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_SCORING: {"status": "queued", "score": None, "duration_ms": 0},
        STAGE_AI_ANALYSIS: {"status": "queued", "items": 0, "duration_ms": 0},
    }


# ---------------------------------------------------------------------------
# Job limits (§29 — env-configurable, transported with every job).
# ---------------------------------------------------------------------------
class ScanJobLimits(BaseModel):
    max_hosts: int = Field(default=500, ge=1)
    max_ports: int = Field(default=100, ge=1)
    stage_timeout_seconds: int = Field(default=300, ge=10)
    nuclei_concurrency: int = Field(default=1, ge=1, le=4)
    nuclei_max_hosts: int = Field(default=50, ge=0)


# ---------------------------------------------------------------------------
# Job payload — what the worker receives when it claims a scan (§15, §21).
# ---------------------------------------------------------------------------
class ScanJob(BaseModel):
    version: int = 1
    scan_id: str
    organization_id: str
    domain_id: str
    target: str
    target_type: str = "domain"
    # Authorization scope: the worker may only touch hosts under these suffixes.
    scope: List[str]
    created_at: str
    authorization_context: Dict[str, Any] = Field(default_factory=dict)
    limits: ScanJobLimits = Field(default_factory=ScanJobLimits)
    lease_expires_at: str


# ---------------------------------------------------------------------------
# Progress update — worker → core (§22 lifecycle stages).
# ---------------------------------------------------------------------------
class ProgressUpdate(BaseModel):
    stage: str
    status: str
    items: int = 0
    duration_ms: int = 0
    error: Optional[str] = None

    @field_validator("stage")
    @classmethod
    def _known_stage(cls, v: str) -> str:
        if v not in ALL_STAGES:
            raise ValueError(f"unknown stage: {v}")
        return v

    @field_validator("status")
    @classmethod
    def _known_status(cls, v: str) -> str:
        if v not in VALID_PROGRESS_STATUSES:
            raise ValueError(f"unknown status: {v}")
        return v


# ---------------------------------------------------------------------------
# Observation batch — raw scanner output, never business decisions (§19).
# ---------------------------------------------------------------------------
class ObservationSubmit(BaseModel):
    stage: str
    data: Dict[str, Any]

    @field_validator("stage")
    @classmethod
    def _observation_stage(cls, v: str) -> str:
        if v not in OBSERVATION_STAGES:
            raise ValueError(f"stage {v} does not produce observations")
        return v


# ---------------------------------------------------------------------------
# Job completion / failure.
# ---------------------------------------------------------------------------
class JobComplete(BaseModel):
    stats: Dict[str, Any] = Field(default_factory=dict)


class JobFail(BaseModel):
    stage: Optional[str] = None
    error: str = Field(min_length=1, max_length=2000)
