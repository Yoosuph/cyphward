"""Build the scanned domain's compliance evidence rows at scan finalisation.

Called by the finaliser before the completion transaction; the rows are then
inserted by `scan_execution.finish_assessment` under the held claim (inside a
savepoint, so evidence can never fail an assessment). Reads here run inside
the finaliser's execution context and are fenced like every other Core read.
"""
from typing import Any, Dict, List

from backend.app.compliance import mapping
from backend.app.compliance.register import REGISTER, tool_requirements
from backend.app.core.database import execute_query
from backend.app.risk.coverage import _open_ports


def evidence_for_scan(*, org_id: str, domain_id: str, scan_id: str, coverage: Any,
                      observations: Dict[str, Any], completed_at: Any) -> List[Dict[str, Any]]:
    findings = execute_query(
        "SELECT f.id, f.title, f.category, f.evidence, f.status FROM findings f "
        "JOIN assets a ON a.id = f.asset_id AND a.org_id = f.org_id "
        "WHERE f.org_id = %s AND a.domain_id = %s AND f.status != 'resolved'",
        (org_id, domain_id)) or []
    ports = observations.get("ports") if isinstance(observations.get("ports"), dict) else {}
    open_ports = {host: sorted(found) for host, found in _open_ports(ports).items()}
    return mapping.domain_rows(tool_requirements(), coverage, findings, org_id=str(org_id), domain_id=str(domain_id),
                               scan_id=str(scan_id), observed_at=completed_at, register_version=REGISTER["version"],
                               open_ports=open_ports)
