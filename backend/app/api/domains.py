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

router = APIRouter(prefix="/api/v1/domains", tags=["Domains"])


class AddDomainRequest(BaseModel):
    domain: str


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
