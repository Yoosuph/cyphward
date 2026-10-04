"""
Cyphward Domains API Router
Manages enterprise domains, cryptographic DNS TXT verification tokens, and verification status.
Only VERIFIED domains may enter the scanning pipeline (spec §10, §40).
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from backend.app.core.database import execute_one, execute_query
from backend.app.scanner.domain_verifier import generate_verification_token, verify_domain_dns_txt
from backend.app.core.auth import get_current_org, require_admin, log_audit, membership_role
from backend.app.core.plans import entitlements_for, require_quota, usage_for_org

router = APIRouter(prefix="/api/v1/domains", tags=["Domains"])


class AddDomainRequest(BaseModel):
    domain: str


class AddHostRequest(BaseModel):
    hostname: str


def _normalize_hostname(raw: str) -> str:
    host = (raw or "").strip().lower()
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.split("/")[0].split(":")[0].rstrip(".")
    if not host or "." not in host or " " in host or len(host) > 253:
        raise HTTPException(status_code=400, detail=f"Invalid hostname '{raw}'.")
    if any(not (ch.isalnum() or ch in "-.") for ch in host):
        raise HTTPException(status_code=400, detail=f"Invalid hostname '{raw}'.")
    return host


def _get_owned_domain(domain_id: str, org_id: str) -> Dict[str, Any]:
    domain = execute_one(
        "SELECT * FROM domains WHERE id = %s AND org_id = %s", (domain_id, org_id)
    )
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found.")
    return domain


@router.get("/{domain_id}/hosts")
def list_monitored_hosts(
    domain_id: str,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    """Owner-registered hosts for a domain (probed every scan)."""
    _get_owned_domain(domain_id, org["id"])
    rows = execute_query(
        "SELECT id, hostname, created_at FROM monitored_hosts "
        "WHERE org_id = %s AND domain_id = %s ORDER BY hostname ASC",
        (org["id"], domain_id),
    )
    return {"hosts": rows or []}


@router.post("/{domain_id}/hosts", status_code=201)
def add_monitored_host(
    domain_id: str,
    req: AddHostRequest,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Register a hostname under a VERIFIED domain (admin/owner).

    The name must be the domain itself or its subdomain — never anything
    outside the tenant's verified scope. Shares the plan's domain budget.
    """
    domain = _get_owned_domain(domain_id, org["id"])
    if domain["verification_status"] != "verified":
        raise HTTPException(
            status_code=400,
            detail="Verify the domain before registering hosts for it.",
        )
    hostname = _normalize_hostname(req.hostname)
    apex = domain["domain"].strip().lower()
    if hostname != apex and not hostname.endswith("." + apex):
        raise HTTPException(
            status_code=400,
            detail=f"'{hostname}' is outside the verified scope of {apex}.",
        )
    existing = execute_one(
        "SELECT id FROM monitored_hosts WHERE org_id = %s AND hostname = %s",
        (org["id"], hostname),
    )
    if existing:
        raise HTTPException(status_code=400, detail=f"{hostname} is already registered.")
    usage = usage_for_org(str(org["id"]))
    ent = entitlements_for(org)
    limit = ent.get("max_domains")
    if limit is not None and usage["domains"] + len(
        execute_query(
            "SELECT id FROM monitored_hosts WHERE org_id = %s", (org["id"],)
        ) or []
    ) >= limit:
        raise HTTPException(
            status_code=402,
            detail=f"Domain budget reached for the {ent['label']} plan "
                   f"({usage['domains']} domains, limit {limit}).",
        )
    row = execute_one(
        """
        INSERT INTO monitored_hosts (org_id, domain_id, hostname, added_by)
        VALUES (%s, %s, %s, %s)
        RETURNING id, hostname, created_at
        """,
        (org["id"], domain_id, hostname, org.get("current_user_id")),
    )
    log_audit(org["id"], org.get("current_user_id"), "domain.host_registered",
              "monitored_host", str(row["id"]), {"hostname": hostname})
    return {"host": row}


@router.delete("/{domain_id}/hosts/{host_id}")
def remove_monitored_host(
    domain_id: str,
    host_id: str,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Remove a registered host (admin/owner)."""
    _get_owned_domain(domain_id, org["id"])
    deleted = execute_one(
        "DELETE FROM monitored_hosts WHERE id = %s AND org_id = %s AND domain_id = %s RETURNING id",
        (host_id, org["id"], domain_id),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Registered host not found.")
    log_audit(org["id"], org.get("current_user_id"), "domain.host_removed",
              "monitored_host", str(host_id), {})
    return {"removed": True}


@router.get("")
def list_domains(org: Dict[str, Any] = Depends(get_current_org)) -> List[Dict[str, Any]]:
    """List all registered domains with verification status and asset telemetry."""
    domains = execute_query("""
        SELECT d.*,
               COUNT(DISTINCT a.id) as asset_count,
               COUNT(DISTINCT s.id) as scan_count
        FROM domains d
        LEFT JOIN assets a ON a.domain_id = d.id
        LEFT JOIN scans s ON s.domain_id = d.id
        WHERE d.org_id = %s
        GROUP BY d.id
        ORDER BY d.created_at ASC
    """, (org["id"],))

    return domains


@router.post("")
def add_domain(
    req: AddDomainRequest,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Register a new domain and generate a sovereign DNS TXT verification token."""
    domain_clean = req.domain.strip().lower()
    if "://" in domain_clean:
        domain_clean = domain_clean.split("://")[1]
    domain_clean = domain_clean.split("/")[0].split(":")[0]

    if not domain_clean or "." not in domain_clean or " " in domain_clean or len(domain_clean) > 253:
        raise HTTPException(status_code=400, detail=f"Invalid domain name '{req.domain}'. Please provide a valid fully qualified domain name.")

    token = generate_verification_token()

    existing = execute_one("SELECT id FROM domains WHERE org_id = %s AND domain = %s", (org["id"], domain_clean))
    if existing:
        raise HTTPException(status_code=400, detail=f"Domain {domain_clean} is already added.")

    # Plan entitlement: domain-count limit (review P1 line 33).
    require_quota(org, "domains")

    created = execute_one("""
        INSERT INTO domains (org_id, domain, verification_status, verification_token)
        VALUES (%s, %s, 'pending', %s)
        RETURNING *;
    """, (org["id"], domain_clean, token))

    log_audit(org["id"], org.get("current_user_id"), "domain.added", "domain", str(created["id"]),
              {"domain": domain_clean})

    return {
        "message": f"Domain {domain_clean} added. Configure DNS TXT record to complete verification.",
        "domain": created,
        "dns_instructions": {
            "record_type": "TXT",
            # Bare host only: registrar panels append the domain themselves,
            # so showing the FQDN here caused "_cyphward.x.com.x.com".
            "host": "_cyphward",
            "value": f"cyphward-verification={token}",
            "ttl": 300,
        }
    }


@router.post("/{domain_id}/verify")
async def verify_domain(
    domain_id: str,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Perform real DNS TXT verification for domain ownership (no simulation paths)."""
    domain_row = execute_one(
        "SELECT * FROM domains WHERE id = %s AND org_id = %s",
        (domain_id, org["id"]),
    )
    if not domain_row:
        raise HTTPException(status_code=404, detail="Domain not found.")

    domain_name = domain_row["domain"]
    token = domain_row["verification_token"]

    if domain_row["verification_status"] == "verified":
        return {
            "status": "verified",
            "message": f"Domain {domain_name} is already verified.",
            "details": {"domain": domain_name, "verified": True},
        }

    check_result = await verify_domain_dns_txt(domain_name, token)
    is_verified = bool(check_result.get("verified"))

    if is_verified:
        execute_query("""
            UPDATE domains
            SET verification_status = 'verified', verified_at = now(), updated_at = now()
            WHERE id = %s AND org_id = %s
        """, (domain_id, org["id"]))
        log_audit(org["id"], org.get("current_user_id"), "domain.verified", "domain", domain_id,
                  {"domain": domain_name})

        return {
            "status": "verified",
            "message": f"Domain {domain_name} verified successfully!",
            "details": check_result
        }

    # Stays pending per spec lifecycle (PENDING -> VERIFIED / EXPIRED / REVOKED)
    execute_query(
        "UPDATE domains SET verification_status = 'pending', updated_at = now() WHERE id = %s AND org_id = %s",
        (domain_id, org["id"]),
    )
    return {
        "status": "pending",
        "message": f"Verification failed for {domain_name}. Expected DNS TXT record with '{token}' was not detected.",
        "details": check_result
    }


@router.delete("/{domain_id}")
def delete_domain(domain_id: str, org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Delete a domain and associated assets (admin/owner only)."""
    deleted = execute_one(
        "DELETE FROM domains WHERE id = %s AND org_id = %s RETURNING id, domain",
        (domain_id, org["id"]),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Domain not found.")

    log_audit(org["id"], org.get("current_user_id"), "domain.deleted", "domain", domain_id,
              {"domain": deleted.get("domain")})
    return {"message": "Domain removed."}
