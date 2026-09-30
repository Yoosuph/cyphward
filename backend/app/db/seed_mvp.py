"""
Run database migration and seed data for Cyphward MVP.
"""
import json
import psycopg
from backend.app.core.config import DATABASE_URL

import sys

def migrate_and_seed(reset: bool = False):
    print(f"Connecting to database...")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # 1. Run migrations (schema + spec alignment), in filename order
            import glob
            for path in sorted(glob.glob("supabase/migrations/*.sql")):
                with open(path) as f:
                    cur.execute(f.read())
                print(f"Applied {path}")

            if reset:
                print("Resetting database tables...")
                cur.execute("""
                    TRUNCATE organizations, profiles, organization_members, domains, assets, scans, scan_results, findings, score_snapshots CASCADE;
                """)
                conn.commit()

            # 2. Check if default org exists
            cur.execute("SELECT id FROM organizations WHERE slug = 'acme-africa' LIMIT 1")
            row = cur.fetchone()
            if not row or reset:
                print("Seeding initial organization and assets...")
                cur.execute("""
                    INSERT INTO organizations (id, name, slug, cac_rc, sector, plan)
                    VALUES (
                        'a0000000-0000-0000-0000-000000000001',
                        'Acme Africa Holdings Ltd',
                        'acme-africa',
                        'RC-1849204',
                        'Fintech & Digital Commerce',
                        'Enterprise Defense'
                    ) RETURNING id;
                """)
                org_id = cur.fetchone()[0]

                # Seed user
                cur.execute("""
                    INSERT INTO profiles (id, email, full_name, role)
                    VALUES (
                        'b0000000-0000-0000-0000-000000000001',
                        'ciso@acmetraders.ng',
                        'Aliyu Danladi (CISO)',
                        'Chief Information Security Officer'
                    ) RETURNING id;
                """)
                user_id = cur.fetchone()[0]

                # Seed membership
                cur.execute("""
                    INSERT INTO organization_members (user_id, org_id, role)
                    VALUES (%s, %s, 'owner');
                """, (user_id, org_id))

                # Seed domain
                cur.execute("""
                    INSERT INTO domains (id, org_id, domain, verification_status, verification_token, verified_at)
                    VALUES (
                        'd0000000-0000-0000-0000-000000000001',
                        %s,
                        'acmetraders.ng',
                        'verified',
                        'cyphward-verify-8ef209ac15b8',
                        now() - interval '2 days'
                    ) RETURNING id;
                """, (org_id,))
                domain_id = cur.fetchone()[0]

                # Seed assets
                assets_data = [
                    (
                        'acmetraders.ng',
                        '102.134.88.12',
                        'Web Endpoint',
                        'active',
                        200,
                        json.dumps([{"name": "Nginx", "version": "1.24.0", "category": "Web Server"}, {"name": "Cloudflare", "category": "CDN / WAF"}]),
                        json.dumps({"issuer": "Let's Encrypt", "valid_to": "2026-12-14", "days_remaining": 87, "protocol": "TLSv1.3"}),
                        json.dumps({"A": ["102.134.88.12"], "MX": ["mail.acmetraders.ng"], "TXT": ["v=spf1 include:_spf.google.com ~all"]})
                    ),
                    (
                        'api.acmetraders.ng',
                        '102.134.88.14',
                        'API Gateway',
                        'active',
                        200,
                        json.dumps([{"name": "FastAPI", "version": "0.115.0", "category": "Framework"}, {"name": "Python", "category": "Runtime"}, {"name": "Uvicorn", "category": "ASGI Server"}]),
                        json.dumps({"issuer": "Let's Encrypt", "valid_to": "2026-11-20", "days_remaining": 63, "protocol": "TLSv1.3"}),
                        json.dumps({"A": ["102.134.88.14"]})
                    ),
                    (
                        'mail.acmetraders.ng',
                        '102.134.88.19',
                        'Mail Server',
                        'active',
                        None,
                        json.dumps([{"name": "Postfix", "version": "3.8.1", "category": "MTA"}]),
                        json.dumps({"issuer": "Let's Encrypt", "valid_to": "2026-10-30", "days_remaining": 42, "protocol": "TLSv1.3"}),
                        json.dumps({"A": ["102.134.88.19"], "MX": ["10 mail.acmetraders.ng"]})
                    ),
                    (
                        'auth.acmetraders.ng',
                        '102.134.88.25',
                        'Web Endpoint',
                        'active',
                        200,
                        json.dumps([{"name": "OAuth2 / OIDC", "category": "Identity Provider"}, {"name": "Nginx", "category": "Reverse Proxy"}]),
                        json.dumps({"issuer": "Let's Encrypt", "valid_to": "2026-11-05", "days_remaining": 48, "protocol": "TLSv1.3"}),
                        json.dumps({"A": ["102.134.88.25"]})
                    ),
                    (
                        'admin.internal.acmetraders.ng',
                        '102.134.88.40',
                        'Web Endpoint',
                        'active',
                        403,
                        json.dumps([{"name": "Apache", "version": "2.4.52", "category": "Web Server"}]),
                        json.dumps({"issuer": "Internal CA", "valid_to": "2027-01-01", "days_remaining": 105, "protocol": "TLSv1.2"}),
                        json.dumps({"A": ["102.134.88.40"]})
                    ),
                    (
                        'vpn.acmetraders.ng',
                        '102.134.88.50',
                        'VPN Gateway',
                        'active',
                        None,
                        json.dumps([{"name": "OpenVPN Access Server", "category": "VPN"}]),
                        json.dumps({"issuer": "Let's Encrypt", "valid_to": "2026-10-15", "days_remaining": 27, "protocol": "TLSv1.2"}),
                        json.dumps({"A": ["102.134.88.50"]})
                    )
                ]

                asset_ids = []
                for hostname, ip, atype, status, http_s, techs, tls, dns in assets_data:
                    cur.execute("""
                        INSERT INTO assets (org_id, domain_id, hostname, ip_address, asset_type, status, http_status, technologies, tls_info, dns_records)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                        RETURNING id;
                    """, (org_id, domain_id, hostname, ip, atype, status, http_s, techs, tls, dns))
                    asset_ids.append(cur.fetchone()[0])

                # Seed completed scan
                stage_progress = {
                    "discovery": {"status": "completed", "items": 6, "duration_ms": 1420},
                    "dns": {"status": "completed", "items": 18, "duration_ms": 980},
                    "http": {"status": "completed", "items": 4, "duration_ms": 2340},
                    "security_checks": {"status": "completed", "items": 12, "duration_ms": 3120},
                    "normalization": {"status": "completed", "items": 5, "duration_ms": 450},
                    "scoring": {"status": "completed", "score": 74, "duration_ms": 310}
                }

                cur.execute("""
                    INSERT INTO scans (id, org_id, domain_id, status, score, stage_progress, current_stage, started_at, completed_at)
                    VALUES (
                        'e0000000-0000-0000-0000-000000000001',
                        %s, %s, 'completed', 74, %s::jsonb, 'completed',
                        now() - interval '3 hours', now() - interval '2 hours 50 minutes'
                    ) RETURNING id;
                """, (org_id, domain_id, json.dumps(stage_progress)))
                scan_id = cur.fetchone()[0]

                # Seed findings
                findings_data = [
                    (
                        scan_id,
                        asset_ids[0], # acmetraders.ng
                        org_id,
                        "Strict-Transport-Security (HSTS) Missing on Subdomains",
                        "The Strict-Transport-Security HTTP response header is missing the 'includeSubDomains' directive. Attackers on the same network could exploit insecure HTTP connections to subdomains to perform man-in-the-middle attacks.",
                        "high",
                        "HTTP Headers",
                        json.dumps({
                            "url": "https://acmetraders.ng",
                            "observed_header": "Strict-Transport-Security: max-age=31536000",
                            "required_header": "Strict-Transport-Security: max-age=31536000; includeSubDomains; preload",
                            "status_code": 200,
                            "curl_reproduction": "curl -I https://acmetraders.ng | grep -i strict-transport-security"
                        }),
                        "Update the web server configuration to include 'includeSubDomains' and 'preload' in the Strict-Transport-Security header.",
                        "open"
                    ),
                    (
                        scan_id,
                        asset_ids[0],
                        org_id,
                        "Permissive Email DMARC Policy (p=none)",
                        "The published DMARC policy for acmetraders.ng specifies 'p=none'. This mode is monitoring only and does not instruct receiving mail servers to reject or quarantine spoofed emails claiming to come from this domain.",
                        "critical",
                        "DNS & Email Security",
                        json.dumps({
                            "dns_query": "_dmarc.acmetraders.ng",
                            "record_type": "TXT",
                            "observed_value": "v=DMARC1; p=none; sp=none; rua=mailto:dmarc@acmetraders.ng",
                            "risk_analysis": "Allows spoofed transactional emails to pass verification checks across Yahoo, Google Workspace, and Outlook."
                        }),
                        "Elevate DMARC policy to 'p=quarantine' or 'p=reject' after validating legitimate sender alignment reports (rua).",
                        "open"
                    ),
                    (
                        scan_id,
                        asset_ids[4], # admin.internal
                        org_id,
                        "Server Version Disclosed in HTTP Header",
                        "The web server exposes its exact software name and version ('Apache/2.4.52 (Ubuntu)') in the HTTP Server banner. This provides reconnaissance intelligence to attackers searching for CVEs specific to this build.",
                        "medium",
                        "Information Disclosure",
                        json.dumps({
                            "url": "https://admin.internal.acmetraders.ng",
                            "server_header": "Apache/2.4.52 (Ubuntu)",
                            "cve_references": ["CVE-2022-22720", "CVE-2022-23943"],
                            "curl_reproduction": "curl -sI https://admin.internal.acmetraders.ng | grep -i server"
                        }),
                        "Configure 'ServerTokens Prod' and 'ServerSignature Off' in apache2.conf to suppress detailed version disclosure.",
                        "open"
                    ),
                    (
                        scan_id,
                        asset_ids[1], # api
                        org_id,
                        "Missing Content-Security-Policy (CSP) Header",
                        "The application response does not include a Content-Security-Policy header. A strong CSP restricts the sources from which scripts, styles, and other resources can be loaded, mitigating Cross-Site Scripting (XSS).",
                        "medium",
                        "HTTP Headers",
                        json.dumps({
                            "url": "https://api.acmetraders.ng",
                            "observed_headers": ["Content-Type: application/json", "X-Request-Id: req_7b9a1"],
                            "missing_header": "Content-Security-Policy"
                        }),
                        "Define and enforce an appropriate Content-Security-Policy header (e.g. default-src 'self'; frame-ancestors 'none').",
                        "open"
                    ),
                    (
                        scan_id,
                        asset_ids[5], # vpn
                        org_id,
                        "TLS Certificate Expiring within 30 Days",
                        "The SSL/TLS certificate for vpn.acmetraders.ng expires in 27 days. If not renewed, client VPN tunnels and browser connections will display security warnings or terminate.",
                        "high",
                        "SSL/TLS",
                        json.dumps({
                            "hostname": "vpn.acmetraders.ng",
                            "port": 443,
                            "issuer": "Let's Encrypt Authority X3",
                            "valid_to": "2026-10-15T08:00:00Z",
                            "days_remaining": 27
                        }),
                        "Trigger automated ACME certificate renewal via certbot or let's encrypt client.",
                        "open"
                    ),
                    (
                        scan_id,
                        asset_ids[0],
                        org_id,
                        "SPF Record Configured with Softfail (~all)",
                        "The SPF record uses '~all' instead of '-all' (Hardfail). Unauthorized mail servers sending messages on behalf of acmetraders.ng are only tagged with a soft-fail rather than rejected outright.",
                        "low",
                        "DNS & Email Security",
                        json.dumps({
                            "record": "v=spf1 include:_spf.google.com ~all",
                            "domain": "acmetraders.ng"
                        }),
                        "Change '~all' to '-all' once all legitimate IP ranges and outgoing relays have been incorporated.",
                        "open"
                    ),
                    (
                        scan_id,
                        asset_ids[0],
                        org_id,
                        "Modern TLS 1.3 Ciphers Verified",
                        "The host successfully negotiates TLS 1.3 with forward secrecy ciphers (TLS_AES_256_GCM_SHA384). Weak legacy protocols (SSLv3, TLS 1.0, 1.1) are disabled.",
                        "info",
                        "SSL/TLS",
                        json.dumps({
                            "negotiated_protocol": "TLSv1.3",
                            "cipher_suite": "TLS_AES_256_GCM_SHA384",
                            "weak_protocols_disabled": ["SSLv2", "SSLv3", "TLSv1.0", "TLSv1.1"]
                        }),
                        "Maintain current cryptographic configuration and continue regular TLS compliance audits.",
                        "open"
                    )
                ]

                for s_id, a_id, o_id, title, desc, sev, cat, ev, rem, st in findings_data:
                    cur.execute("""
                        INSERT INTO findings (scan_id, asset_id, org_id, title, description, severity, category, evidence, remediation, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s);
                    """, (s_id, a_id, o_id, title, desc, sev, cat, ev, rem, st))

                # Seed score snapshots
                snapshots = [
                    (org_id, domain_id, 71, "7 days"),
                    (org_id, domain_id, 73, "4 days"),
                    (org_id, domain_id, 74, "0 days"),
                ]
                for o_id, d_id, sc, off in snapshots:
                    subscores = [
                        {"name": "Network & DNS", "score": 19, "max": 25, "status": "OK"},
                        {"name": "Web & Apps", "score": 27, "max": 35, "status": "Good"},
                        {"name": "Encryption", "score": 21, "max": 25, "status": "Good"},
                        {"name": "Exposure", "score": 8, "max": 15, "status": "Needs work"}
                    ]
                    factors = [
                        {"impact": "+5", "type": "positive", "label": "Strong encryption (TLS 1.3) is active"},
                        {"impact": "+4", "type": "positive", "label": "Cloudflare WAF enabled on primary domain"},
                        {"impact": "-8", "type": "negative", "label": "Email DMARC policy set to p=none"},
                        {"impact": "-5", "type": "negative", "label": "HSTS header missing includeSubDomains"}
                    ]
                    cur.execute(f"""
                        INSERT INTO score_snapshots (org_id, domain_id, score, subscores, factors, created_at)
                        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, now() - interval '{off}');
                    """, (o_id, d_id, sc, json.dumps(subscores), json.dumps(factors)))

                conn.commit()
                print("Seeding completed successfully!")
            else:
                print("Organization already exists. Schema is up to date.")

if __name__ == "__main__":
    reset_db = "--reset" in sys.argv
    migrate_and_seed(reset=reset_db)
