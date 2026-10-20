"""Core <-> browser worker contract for the first-visit cookie observation (C2b).

Pydantic-only, no FastAPI/DB, importable from Core and from the browser worker
image. The observation is what a headless browser saw on a first visit: it is
raw evidence, never a statement about whether a site follows any law.

Core validates the result with these exact models (extra fields rejected,
every string and list bounded) before anything is stored.
"""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PRIVACY_BROWSER_CAPABILITY = "privacy_browser"
CAPABILITIES_HEADER = "X-Scanner-Capabilities"
JOB_TYPE_CONSENT = "cookie_consent_observation"
OBSERVATION_VERSION = 1
BROWSER_PROTOCOL_VERSION = 1

# Hard ceilings. The worker clamps whatever the job asks for to these, and the
# schema below refuses anything bigger, so a compromised side cannot widen them.
MAX_PAGE_TIMEOUT_SECONDS = 45
MAX_JOB_SECONDS = 90
MAX_SUBREQUESTS = 150
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_COOKIES = 100
MAX_THIRD_PARTY_HOSTS = 100
MAX_RESULT_BODY_BYTES = 64 * 1024

LIFETIME_BUCKETS = ("session", "under_1_day", "under_30_days", "under_1_year", "over_1_year")
SAME_SITE_VALUES = ("strict", "lax", "none", "unset")
REJECT_LEVELS = ("same_level", "less_prominent", "not_detected")
# Names only, never page text: the marker that matched a common consent manager.
CMS_MARKERS = ("onetrust", "cookiebot", "usercentrics", "didomi", "quantcast", "trustarc", "cookieyes",
               "osano", "complianz", "iubenda", "cookie_law_info", "klaro", "termly", "generic_dialog")

_HOST = r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$"
_NO_CONTROL = r"^[^\x00-\x1f\x7f]*$"
_ID = r"^[A-Za-z0-9-]{1,64}$"


class BrowserLimits(BaseModel):
    page_timeout_seconds: int = Field(default=MAX_PAGE_TIMEOUT_SECONDS, ge=5, le=MAX_PAGE_TIMEOUT_SECONDS)
    job_timeout_seconds: int = Field(default=MAX_JOB_SECONDS, ge=10, le=MAX_JOB_SECONDS)
    max_requests: int = Field(default=MAX_SUBREQUESTS, ge=1, le=MAX_SUBREQUESTS)
    max_total_bytes: int = Field(default=MAX_TOTAL_BYTES, ge=1024, le=MAX_TOTAL_BYTES)


class BrowserJob(BaseModel):
    """What the browser worker receives when it claims a job."""
    version: Literal[1] = 1
    job_type: Literal["cookie_consent_observation"]
    job_id: str = Field(pattern=_ID)
    organization_id: str = Field(pattern=_ID)
    domain_id: str = Field(pattern=_ID)
    target: str = Field(min_length=1, max_length=253)
    scope: List[str] = Field(min_length=1, max_length=5)
    url: str = Field(min_length=8, max_length=300)
    authorization_context: Dict[str, object] = Field(default_factory=dict)
    limits: BrowserLimits = Field(default_factory=BrowserLimits)
    lease_expires_at: str
    claim_generation: int = Field(ge=1)
    claim_token: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", repr=False)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObservedCookie(_Strict):
    name: str = Field(min_length=1, max_length=128, pattern=_NO_CONTROL)
    domain: str = Field(min_length=1, max_length=253, pattern=_HOST)
    secure: bool
    http_only: bool
    same_site: Literal["strict", "lax", "none", "unset"]
    lifetime: Literal["session", "under_1_day", "under_30_days", "under_1_year", "over_1_year"]
    third_party: bool


class HostCount(_Strict):
    host: str = Field(min_length=1, max_length=253, pattern=_HOST)
    count: int = Field(ge=1, le=MAX_SUBREQUESTS * 2)


class RequestSummary(_Strict):
    total: int = Field(ge=0, le=MAX_SUBREQUESTS * 2)
    first_party: int = Field(ge=0, le=MAX_SUBREQUESTS * 2)
    third_party_hosts: List[HostCount] = Field(default_factory=list, max_length=MAX_THIRD_PARTY_HOSTS)

    @model_validator(mode="after")
    def _consistent(self):
        counted = self.first_party + sum(h.count for h in self.third_party_hosts)
        if counted > self.total:
            raise ValueError("request counts exceed total")
        if len({h.host for h in self.third_party_hosts}) != len(self.third_party_hosts):
            raise ValueError("duplicate host")
        return self


class BannerObservation(_Strict):
    detected: bool
    in_first_view: bool
    cms_marker: Optional[Literal["onetrust", "cookiebot", "usercentrics", "didomi", "quantcast", "trustarc",
                                 "cookieyes", "osano", "complianz", "iubenda", "cookie_law_info", "klaro",
                                 "termly", "generic_dialog"]] = None
    accept_control: bool
    reject_control: Literal["same_level", "less_prominent", "not_detected"]

    @model_validator(mode="after")
    def _consistent(self):
        if not self.detected and (self.in_first_view or self.accept_control or self.reject_control != "not_detected"):
            raise ValueError("controls reported without a detected banner")
        return self


class Timings(_Strict):
    navigation_ms: int = Field(ge=0, le=MAX_JOB_SECONDS * 1000)
    settle_ms: int = Field(ge=0, le=MAX_JOB_SECONDS * 1000)
    total_ms: int = Field(ge=0, le=MAX_JOB_SECONDS * 1000 + 30_000)


class Caps(_Strict):
    requests: bool = False
    bytes: bool = False
    cookies: bool = False
    page_timeout: bool = False


class ConsentObservation(_Strict):
    version: Literal[1] = 1
    final_url: str = Field(min_length=8, max_length=300, pattern=r"^https?://[^\s]+$")
    browser_version: str = Field(min_length=1, max_length=64, pattern=_NO_CONTROL)
    cookies: List[ObservedCookie] = Field(default_factory=list, max_length=MAX_COOKIES)
    requests: RequestSummary
    banner: BannerObservation
    timings: Timings
    caps: Caps = Field(default_factory=Caps)

    @field_validator("final_url")
    @classmethod
    def _no_query(cls, v: str) -> str:
        # Query strings and fragments can carry tokens; the worker strips them.
        if "?" in v or "#" in v:
            raise ValueError("final_url must not carry a query or fragment")
        return v


class JobFailure(_Strict):
    error: str = Field(min_length=1, max_length=500, pattern=_NO_CONTROL)
    reason: Literal["refused_address", "off_scope_redirect", "timeout", "navigation_failed",
                    "browser_error", "invalid_job"] = "browser_error"
