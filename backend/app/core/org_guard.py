"""Guardrails for deleting an organisation from the owner console (docs/admin-delete-org/README.md).

* Restore window: a soft-deleted organisation can be restored for RESTORE_WINDOW_DAYS days from deleted_at; the
  purge is possible only after that. Both are worked out with the database clock (now()).
* Protected organisations: the platform's sample-data demo organisation (core/demo_org.DEMO_ORG_ID), the INNOVATECH
  organisation (INNOVATECH_ORG_ID_BUILTIN, plus any id in the INNOVATECH_ORG_ID environment variable), the public
  demo workspace (DEMO_LOGIN_ORG_ID) and any organisation whose name contains "innovatech" (letters only, any case)
  are refused for soft delete and purge unless OWNER_ALLOW_PROTECTED_ORG_DELETE is "true". The flag is off by
  default and read on every request.
* Paid subscription: soft delete is refused while the subscription is active, its period has not ended, and it is
  not already set to cancel at the period end. The customer's owner can cancel it, also while suspended
  (core/suspension.py), and the soft delete is then allowed.
* Retention: the purge is refused while any reviewer grant, pack, snapshot, compliance document or evidence file is
  still inside its retention period (organizations.evidence_retention_months, the rule the snapshot and pack pages
  already show as "retain until"). See RETENTION_SQL for the date each record type is measured from. Breach
  incidents have their own fixed period (founder decision, 2026-10-31): the purge is refused while any incident was
  opened within INCIDENT_RETENTION_YEARS years. Attestations are not held back; they go with the organisation.
"""
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from backend.app.core.demo_org import DEMO_ORG_ID

RESTORE_WINDOW_DAYS = 30
OVERRIDE_ENV = "OWNER_ALLOW_PROTECTED_ORG_DELETE"
INNOVATECH_ENV = "INNOVATECH_ORG_ID"
# The production INNOVATECH organisation, protected without any configuration (id supplied with the founder's
# decisions of 2026-10-31). INNOVATECH_ORG_ID can add another id; it cannot remove this one.
INNOVATECH_ORG_ID_BUILTIN = "5e3fe575-caea-4ea9-acab-353e72487d36"
PROTECTED_NAME = "innovatech"
PURGE_WORD = "DELETE"
INCIDENT_RETENTION_YEARS = 6


def _uuid(value: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None


def protected_ids() -> Set[str]:
    ids = {DEMO_ORG_ID, INNOVATECH_ORG_ID_BUILTIN}
    for key in ("DEMO_LOGIN_ORG_ID", INNOVATECH_ENV):
        value = _uuid(os.getenv(key, ""))
        if value:
            ids.add(value)
    return ids


def is_protected(org: Dict[str, Any]) -> bool:
    if _uuid(org.get("id")) in protected_ids():
        return True
    return PROTECTED_NAME in re.sub(r"[^a-z]", "", str(org.get("name") or "").lower())


def override_enabled() -> bool:
    return os.getenv(OVERRIDE_ENV, "").strip().lower() == "true"


def _aware(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def paid_subscription_active(sub: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> bool:
    """An `active` subscription whose period has not ended and that is not set to cancel at the period end."""
    if not sub or (sub.get("status") or "").strip().lower() != "active":
        return False
    if sub.get("cancel_at_period_end"):
        return False
    end = _aware(sub.get("current_period_end"))
    return end is not None and end > (now or datetime.now(timezone.utc))


# Each record is retained until (its date + the organisation's retention months) has passed, the same calendar
# arithmetic as snapshots.store.add_months (PostgreSQL clamps to the month's last day the same way; the purge sets the
# session time zone to UTC first so the day boundary matches). The date used for each record type:
#   reviewer grants     the latest of: granted, revoked (or the expiry if never revoked), and the grant's latest
#                       practitioner review or clause verification
#   packs               issued_at (as packs/store.py shows retain_until)
#   snapshots           created_at (as snapshots/store.py shows retain_until)
#   documents           the latest of: generated_at and the document's latest approval
#   evidence files      the latest of: uploaded_at and removed_at; removed files count too
#   breach incidents    a fixed INCIDENT_RETENTION_YEARS years (not the organisation's setting) from when the incident
#                       was opened: the latest of detected_at, became_aware_at and created_at
# Only packs and snapshots had a written retention date before; grants, documents and files use the same period from
# the dates above (founder decision, 2026-10-31; docs/admin-delete-org/README.md).
RETENTION_SQL = """
    WITH r AS (SELECT make_interval(months => evidence_retention_months) AS keep FROM organizations WHERE id = %(org)s)
    SELECT
      (SELECT count(*) FROM compliance_reviewer_grants g, r
        WHERE g.org_id = %(org)s
          AND GREATEST(g.granted_at, COALESCE(g.revoked_at, g.expires_at),
                       (SELECT max(pr.reviewed_at) FROM compliance_practitioner_reviews pr
                         WHERE pr.org_id = g.org_id AND pr.grant_id = g.id),
                       (SELECT max(cv.verified_at) FROM compliance_clause_verifications cv
                         WHERE cv.org_id = g.org_id AND cv.grant_id = g.id)) + r.keep > now()) AS reviewer_grants,
      (SELECT count(*) FROM evidence_packs p, r
        WHERE p.org_id = %(org)s AND p.issued_at + r.keep > now()) AS packs,
      (SELECT count(*) FROM assessment_snapshots s, r
        WHERE s.org_id = %(org)s AND s.created_at + r.keep > now()) AS snapshots,
      (SELECT count(*) FROM compliance_documents d, r
        WHERE d.org_id = %(org)s
          AND GREATEST(d.generated_at,
                       (SELECT max(a.approved_at) FROM compliance_document_approvals a
                         WHERE a.org_id = d.org_id AND a.document_id = d.id)) + r.keep > now()) AS documents,
      (SELECT count(*) FROM compliance_evidence_files f, r
        WHERE f.org_id = %(org)s AND GREATEST(f.uploaded_at, f.removed_at) + r.keep > now()) AS evidence_files,
      (SELECT count(*) FROM compliance_incidents i
        WHERE i.org_id = %(org)s
          AND GREATEST(i.detected_at, i.became_aware_at, i.created_at)
              + make_interval(years => %(incident_years)s) > now()) AS incidents,
      (SELECT evidence_retention_months FROM organizations WHERE id = %(org)s) AS retention_months
"""

RETAINED_KINDS = ("reviewer_grants", "packs", "snapshots", "documents", "evidence_files", "incidents")


def retention_counts(cur, org_id: str) -> Dict[str, int]:
    cur.execute(RETENTION_SQL, {"org": org_id, "incident_years": INCIDENT_RETENTION_YEARS})
    row = cur.fetchone() or {}
    counts = {kind: int(row.get(kind) or 0) for kind in RETAINED_KINDS}
    counts["retention_months"] = int(row.get("retention_months") or 0)
    return counts
