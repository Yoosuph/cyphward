"""Third-party hosts' response checks at finalisation, on the real test database.

A mail provider's click-tracking host (CNAME to the provider, 301 to the
provider's own domain) is omitted from the HTTP stage as third_party_service.
Its response belongs to the provider, so no header/banner findings may be
raised from it, and findings an older scan raised there are resolved. The
customer's own hosts are still checked as before.
"""
import asyncio
from uuid import uuid4

from backend.app.core import scan_admission as admission, scan_execution as ex
from backend.app.scanner import ip_guard
from backend.app.workflows import inngest_workflow as wf
from backend.tests.test_scan_execution_postgres import (  # noqa: F401 (fixtures)
    admission_db, disposable_postgres_url, execution_db, no_external,
)

HEADER_TITLES = {
    "Strict-Transport-Security (HSTS) Header Missing", "Missing Content-Security-Policy (CSP) Header",
    "Missing X-Frame-Options (Clickjacking Protection)", "Missing X-Content-Type-Options: nosniff Header",
    "Server Software Version Disclosed in HTTP Header",
}


def _scan_with_tracking_host(execution_db):
    conn, org, domains = execution_db
    apex = conn.execute("SELECT domain FROM domains WHERE id=%s", (domains[0],)).fetchone()["domain"]
    tracking = f"r.info.{apex}"
    # An earlier scan (before the fix) raised a header finding on the tracking host.
    asset = conn.execute("INSERT INTO assets (org_id, domain_id, hostname, status, last_seen) "
                         "VALUES (%s, %s, %s, 'active', now()) RETURNING id", (org, domains[0], tracking)).fetchone()["id"]
    stale = conn.execute("INSERT INTO findings (org_id, asset_id, title, description, severity, category, evidence, "
                         "remediation, status) VALUES (%s, %s, 'Strict-Transport-Security (HSTS) Header Missing', 'x', "
                         "'high', 'HTTP Headers', '{}'::jsonb, 'x', 'open') RETURNING id", (org, asset)).fetchone()["id"]
    conn.commit()

    sid = str(admission.admit_scan(org, domains[0], request_scope="third-party", request_key=str(uuid4())).scan["id"])
    worker = ex.claim_from_row(ex.claim_recon("worker", "worker", 120, sid))
    answered = {q: {"status": "no_data" if q in ("CNAME", "AAAA") else "answered",
                    "name": f"_dmarc.{apex}" if q == "DMARC" else apex, "record_type": "TXT" if q == "DMARC" else q}
                for q in ("A", "AAAA", "CNAME", "MX", "TXT", "NS", "DMARC")}
    ex.store_observation(worker, "discovery", {"target_selection": {
        "version": 1, "policy": "apex_registered_passive", "requested_hosts": [apex, tracking],
        "selected_hosts": [apex, tracking], "omitted_hosts": {}, "limits": {"max_hosts": 500, "dns_max_hosts": 40}}})
    ex.store_observation(worker, "dns", {"dns_records": [
        {"hostname": apex, "primary_ip": "93.184.216.34",
         "records": {"A": ["93.184.216.34"], "TXT": ["v=spf1 -all"], "DMARC": ["v=DMARC1; p=reject"],
                     "query_coverage": {"version": 1, "queries": answered}}},
        {"hostname": tracking, "primary_ip": "172.246.243.65",
         "records": {"A": ["172.246.243.65"], "CNAME": ["info-example.r.brand.brevosend.com"]}}],
        "attempted_hosts": [apex, tracking], "successful_hosts": [apex, tracking], "failed_hosts": {}})
    ex.store_observation(worker, "http", {"http_probes": [
        {"hostname": apex, "url": f"https://{apex}", "http_status": 200, "error": None,
         "security_headers": {"content-security-policy": "default-src 'self'", "x-frame-options": "DENY",
                              "x-content-type-options": "nosniff"},
         "raw_headers": {}, "tls_info": {"issuer": "Synthetic CA", "valid_to": "2027-01-01T00:00:00Z", "days_remaining": 400}},
        {"hostname": tracking, "url": f"https://{tracking}", "http_status": 301,
         "error": "redirect blocked: img.mailin.fr out of scope", "third_party_redirect": "img.mailin.fr",
         "security_headers": {"x-content-type-options": "nosniff"}, "server_header": "envoy/1.2",
         "raw_headers": {"location": "https://img.mailin.fr/", "server": "envoy/1.2"},
         "tls_info": {"issuer": "Provider CA", "valid_to": "2027-01-01T00:00:00Z", "days_remaining": 400}}],
        "attempted_hosts": [apex, tracking], "successful_hosts": [apex], "failed_hosts": {},
        "omitted_hosts": {tracking: "third_party_service"}})
    ex.store_observation(worker, "ports", {"open_ports": [
        {"hostname": apex, "port": 443, "protocol": "tcp"}, {"hostname": tracking, "port": 443, "protocol": "tcp"}],
        "attempted_hosts": [apex, tracking], "successful_hosts": [apex, tracking], "failed_hosts": {}})
    return ex.handoff_to_core(worker), apex, tracking, asset, stale


def test_third_party_host_gets_no_header_findings_and_old_ones_resolve(execution_db, monkeypatch):
    conn, org, _ = execution_db
    no_external(monkeypatch)
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda host: None)  # no robots.txt network fetch
    core, apex, tracking, tracking_asset, stale = _scan_with_tracking_host(execution_db)

    result = asyncio.run(wf.finalize_scan(core.scan_id, core))
    assert result["status"] == "completed"

    open_on_tracking = {r["title"] for r in conn.execute(
        "SELECT title FROM findings WHERE asset_id = %s AND status != 'resolved'", (tracking_asset,)).fetchall()}
    assert not (open_on_tracking & HEADER_TITLES), open_on_tracking
    assert conn.execute("SELECT status FROM findings WHERE id = %s", (stale,)).fetchone()["status"] == "resolved"

    # The customer's own host is still checked: its missing HSTS is reported.
    open_on_apex = {r["title"] for r in conn.execute(
        "SELECT f.title FROM findings f JOIN assets a ON a.id = f.asset_id "
        "WHERE a.hostname = %s AND a.org_id = %s AND f.status != 'resolved'", (apex, org)).fetchall()}
    assert "Strict-Transport-Security (HSTS) Header Missing" in open_on_apex

    coverage = result["stage_progress"]["scoring"]["coverage"]
    assert {"hostname": tracking, "check": "http.headers", "reason": "third_party_service"} in coverage["omitted_checks"]
    assert coverage["state"] == "complete"
