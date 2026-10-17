"""
Cyphward scanner ↔ core shared contracts (spec §21).

Single source of truth for the job/observation API between FastAPI Core and the
Azure scanner worker. Pydantic-only — no FastAPI, no DB, safe to import from
either side. Do NOT duplicate these models elsewhere.
"""
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Stage model — one ordered list drives progress tracking on both sides.
# ---------------------------------------------------------------------------
STAGE_DISCOVERY = "discovery"
STAGE_DNS = "dns"
STAGE_HTTP = "http"
STAGE_PRIVACY = "privacy"
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
    # Last, so it only ever uses leftover recon budget: an optional observation
    # must never starve the declared checks (ports/TLS) that decide coverage.
    STAGE_PRIVACY,
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

# Optional worker capabilities, negotiated through GET /scanner/protocol. A
# worker runs a capability's stage only when the API advertises it (an older
# API rejects unknown stages); the API records at claim time whether the
# claiming worker has it, so older workers keep working without the stage.
PRIVACY_CAPABILITY = "privacy_v1"
CAPABILITIES_HEADER = "X-Scanner-Capabilities"


def empty_stage_progress() -> Dict[str, Dict[str, Any]]:
    """Initial stage_progress template (queued) for a new scan row."""
    return {
        STAGE_DISCOVERY: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_DNS: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_HTTP: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_PORTS: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_TLS: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_NUCLEI: {"status": "queued", "items": 0, "duration_ms": 0},
        STAGE_PRIVACY: {"status": "queued", "items": 0, "duration_ms": 0},
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
    dns_max_hosts: int = Field(default=40, ge=1)
    max_ports: int = Field(default=100, ge=1)
    stage_timeout_seconds: int = Field(default=300, ge=10)
    recon_timeout_seconds: int = Field(default=900, ge=10)
    tls_max_hosts: int = Field(default=25, ge=0)
    nuclei_concurrency: int = Field(default=1, ge=1, le=4)
    nuclei_max_hosts: int = Field(default=50, ge=0)
    privacy_max_hosts: int = Field(default=5, ge=0)
    privacy_max_pages: int = Field(default=10, ge=1, le=20)


# ---------------------------------------------------------------------------
# Job payload — what the worker receives when it claims a scan (§15, §21).
# ---------------------------------------------------------------------------
class ScanJob(BaseModel):
    version: Literal[2] = 2
    scan_id: str
    organization_id: str
    domain_id: str
    target: str
    target_type: str = "domain"
    # Authorization scope: the worker may only touch hosts under these suffixes.
    scope: List[str]
    # Owner-registered hosts for the domain: probed every scan even when
    # passive discovery misses them (still scope-filtered worker-side).
    seed_hosts: List[str] = Field(default_factory=list)
    created_at: str
    authorization_context: Dict[str, Any] = Field(default_factory=dict)
    limits: ScanJobLimits = Field(default_factory=ScanJobLimits)
    # Which Nuclei tier this scan runs. Older workers ignore the field and keep their own default.
    nuclei_tier: Literal["daily", "weekly"] = "daily"
    lease_expires_at: str
    claim_generation: int = Field(ge=1)
    claim_token: str = Field(min_length=32, max_length=128, pattern=r'^[A-Za-z0-9_-]+$', repr=False)


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
