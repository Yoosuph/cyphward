"""
Seed separate tenants for multi-tenancy:
1. DataGrid Africa (Preserved, user's real verified domain datagrid-ng.com)
2. Lagos Core Switch Ltd (switchcore.ng - Payment Rails & Financial Switching)
3. PanBank Africa (panbank.africa - Commercial Banking & Capital Markets)
4. Acme Africa Holdings Ltd (acmetraders.ng - Fintech & Digital Commerce)
"""
import json
import psycopg
from backend.app.core.config import DATABASE_URL

def seed_tenants():
    print("Connecting to database for multi-tenant seeding...")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # 1. Lagos Core Switch Ltd
            org2_id = 'a0000000-0000-0000-0000-000000000002'
            user2_id = '16fd8260-d223-4f31-8018-06be71bd0747'
            cur.execute("""
                INSERT INTO organizations (id, name, slug, cac_rc, sector, plan)
                VALUES (%s, 'Lagos Core Switch Ltd', 'lagos-core-switch', 'RC-1489201', 'Payment Rails & Financial Switching', 'Scale')
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    slug = EXCLUDED.slug,
                    cac_rc = EXCLUDED.cac_rc,
                    sector = EXCLUDED.sector,
                    plan = EXCLUDED.plan;
            """, (org2_id,))

            cur.execute("""
                INSERT INTO profiles (id, email, full_name, role)
                VALUES (%s, 'compliance@switch.lagos', 'Folake Adeyemi', 'Chief Compliance & DPO')
                ON CONFLICT (id) DO UPDATE SET
                    email = EXCLUDED.email,
                    full_name = EXCLUDED.full_name,
                    role = EXCLUDED.role;
            """, (user2_id,))

            cur.execute("""
                INSERT INTO organization_members (user_id, org_id, role)
                VALUES (%s, %s, 'owner')
                ON CONFLICT (user_id, org_id) DO NOTHING;
            """, (user2_id, org2_id))

            # Domain for Lagos Core Switch
            domain2_id = 'd0000000-0000-0000-0000-000000000002'
            cur.execute("""
                INSERT INTO domains (id, org_id, domain, verification_status, verification_token, verified_at)
                VALUES (%s, %s, 'switchcore.ng', 'verified', 'cyphward-verify-switch-9912a', now() - interval '7 days')
                ON CONFLICT (org_id, domain) DO UPDATE SET
                    verification_status = 'verified',
                    verified_at = now() - interval '7 days';
            """, (domain2_id, org2_id))

            # 2. PanBank Africa
            org3_id = 'a0000000-0000-0000-0000-000000000003'
            user3_id = '866d5517-a25d-4566-8556-b08090b72bea'
            cur.execute("""
                INSERT INTO organizations (id, name, slug, cac_rc, sector, plan)
                VALUES (%s, 'PanBank Africa', 'panbank-africa', 'RC-1738290', 'Commercial Banking & Capital Markets', 'Sovereign')
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    slug = EXCLUDED.slug,
                    cac_rc = EXCLUDED.cac_rc,
                    sector = EXCLUDED.sector,
                    plan = EXCLUDED.plan;
            """, (org3_id,))

            cur.execute("""
                INSERT INTO profiles (id, email, full_name, role)
                VALUES (%s, 'soc@panbank.africa', 'Tariro Moyo', 'SecOps Analyst (Tier 2)')
                ON CONFLICT (id) DO UPDATE SET
                    email = EXCLUDED.email,
                    full_name = EXCLUDED.full_name,
                    role = EXCLUDED.role;
            """, (user3_id,))

            cur.execute("""
                INSERT INTO organization_members (user_id, org_id, role)
                VALUES (%s, %s, 'owner')
                ON CONFLICT (user_id, org_id) DO NOTHING;
            """, (user3_id, org3_id))

            # Domain for PanBank Africa
            domain3_id = 'd0000000-0000-0000-0000-000000000003'
            cur.execute("""
                INSERT INTO domains (id, org_id, domain, verification_status, verification_token, verified_at)
                VALUES (%s, %s, 'panbank.africa', 'verified', 'cyphward-verify-panbank-5519c', now() - interval '14 days')
                ON CONFLICT (org_id, domain) DO UPDATE SET
                    verification_status = 'verified',
                    verified_at = now() - interval '14 days';
            """, (domain3_id, org3_id))

            # 3. Acme Africa Holdings Ltd (SSO)
            org4_id = 'a0000000-0000-0000-0000-000000000004'
            user4_id = 'ec024b7b-40f9-4e89-a048-5bb0ea79ce34'
            cur.execute("""
                INSERT INTO organizations (id, name, slug, cac_rc, sector, plan)
                VALUES (%s, 'Acme Africa Holdings Ltd', 'acme-africa', 'RC-1849204', 'Fintech & Digital Commerce', 'Enterprise Defense')
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    slug = EXCLUDED.slug,
                    cac_rc = EXCLUDED.cac_rc,
                    sector = EXCLUDED.sector,
                    plan = EXCLUDED.plan;
            """, (org4_id,))

            cur.execute("""
                INSERT INTO profiles (id, email, full_name, role)
                VALUES (%s, 'ciso@acmetraders.ng', 'Aliyu Danladi (CISO)', 'Chief Information Security Officer')
                ON CONFLICT (id) DO UPDATE SET
                    email = EXCLUDED.email,
                    full_name = EXCLUDED.full_name,
                    role = EXCLUDED.role;
            """, (user4_id,))

            cur.execute("""
                INSERT INTO organization_members (user_id, org_id, role)
                VALUES (%s, %s, 'owner')
                ON CONFLICT (user_id, org_id) DO NOTHING;
            """, (user4_id, org4_id))

            # Domain for Acme Africa
            domain4_id = 'd0000000-0000-0000-0000-000000000004'
            cur.execute("""
                INSERT INTO domains (id, org_id, domain, verification_status, verification_token, verified_at)
                VALUES (%s, %s, 'acmetraders.ng', 'verified', 'cyphward-verify-acme-7721d', now() - interval '30 days')
                ON CONFLICT (org_id, domain) DO UPDATE SET
                    verification_status = 'verified',
                    verified_at = now() - interval '30 days';
            """, (domain4_id, org4_id))

            # Clean previous mock records for org2, org3, org4
            for oid in [org2_id, org3_id, org4_id]:
                cur.execute("DELETE FROM score_snapshots WHERE org_id = %s", (oid,))
                cur.execute("DELETE FROM findings WHERE org_id = %s", (oid,))
                cur.execute("DELETE FROM scan_results WHERE scan_id IN (SELECT id FROM scans WHERE org_id = %s)", (oid,))
                cur.execute("DELETE FROM scans WHERE org_id = %s", (oid,))
                cur.execute("DELETE FROM assets WHERE org_id = %s", (oid,))

            # =================================================================
            # SEED ASSETS FOR LAGOS CORE SWITCH (org2)
            # =================================================================
            switch_assets = [
                ('switchcore.ng', '197.210.64.12', 'Web Endpoint', 'active', 200,
                 [{"name": "Nginx", "version": "1.25.3", "category": "Reverse Proxy"}, {"name": "Cloudflare", "category": "CDN / WAF"}],
                 {"issuer": "DigiCert Global Root G2", "valid_to": "2026-11-20", "days_remaining": 62, "protocol": "TLSv1.3"},
                 {"A": ["197.210.64.12"], "MX": ["mail.switchcore.ng"], "TXT": ["v=spf1 ip4:197.210.64.0/24 ~all"]}),
                ('api.switchcore.ng', '197.210.64.15', 'API Gateway', 'active', 200,
                 [{"name": "FastAPI", "version": "0.115.2", "category": "Framework"}, {"name": "Python", "category": "Runtime"}],
                 {"issuer": "DigiCert", "valid_to": "2026-12-05", "days_remaining": 77, "protocol": "TLSv1.3"},
                 {"A": ["197.210.64.15"]}),
                ('iso8583.switchcore.ng', '197.210.64.20', 'Settlement Switch', 'active', 403,
                 [{"name": "Erlang OTP", "version": "26.1", "category": "Switching Engine"}, {"name": "ISO 8583 Rail", "category": "Banking Protocol"}],
                 {"issuer": "Sovereign Private CA", "valid_to": "2027-04-10", "days_remaining": 202, "protocol": "TLSv1.2"},
                 {"A": ["197.210.64.20"]}),
                ('ussd-gw.switchcore.ng', '197.210.64.22', 'Telco Gateway', 'active', 200,
                 [{"name": "SMPP Router", "category": "Telco Protocol"}, {"name": "Envoy", "category": "Proxy"}],
                 {"issuer": "Let's Encrypt", "valid_to": "2026-10-18", "days_remaining": 29, "protocol": "TLSv1.3"},
                 {"A": ["197.210.64.22"]}),
                ('settlement.switchcore.ng', '197.210.64.30', 'Core Clearing Rail', 'active', 401,
                 [{"name": "Java Spring Boot", "version": "3.2.1", "category": "Clearing Backend"}],
                 {"issuer": "Sovereign Private CA", "valid_to": "2026-10-01", "days_remaining": 12, "protocol": "TLSv1.0"},
                 {"A": ["197.210.64.30"]}),
            ]
            switch_asset_ids = []
            for host, ip, atype, status, hcode, techs, tls, dns in switch_assets:
                cur.execute("""
                    INSERT INTO assets (org_id, domain_id, hostname, ip_address, asset_type, status, http_status, technologies, tls_info, dns_records)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                    RETURNING id;
                """, (org2_id, domain2_id, host, ip, atype, status, hcode, json.dumps(techs), json.dumps(tls), json.dumps(dns)))
                switch_asset_ids.append(cur.fetchone()[0])

            # SEED SCAN FOR LAGOS CORE SWITCH
            cur.execute("""
                INSERT INTO scans (org_id, domain_id, status, score, stage_progress, current_stage, started_at, completed_at)
                VALUES (%s, %s, 'completed', 64, '{
                    "discovery": {"status": "completed", "items": 5, "duration_ms": 1200},
                    "dns": {"status": "completed", "items": 5, "duration_ms": 850},
                    "http": {"status": "completed", "items": 5, "duration_ms": 2100},
                    "security_checks": {"status": "completed", "items": 14, "duration_ms": 4500},
                    "normalization": {"status": "completed", "items": 4, "duration_ms": 320},
                    "scoring": {"status": "completed", "score": 64, "duration_ms": 180}
                }'::jsonb, 'completed', now() - interval '3 hours', now() - interval '2 hours 55 minutes')
                RETURNING id;
            """, (org2_id, domain2_id))
            switch_scan_id = cur.fetchone()[0]

            # SEED FINDINGS FOR LAGOS CORE SWITCH
            cur.execute("""
                INSERT INTO findings (org_id, scan_id, asset_id, title, description, severity, category, evidence, remediation, status)
                VALUES
                (%s, %s, %s, 'Exposed ISO 8583 Financial Switching Port on Settlement Rail',
                 'The ISO 8583 banking message protocol endpoint responds to external TCP handshakes without IP allowlisting or mutual certificate challenge.',
                 'critical', 'Infrastructure',
                 '{"port": 8583, "response": "ISO-0800-HEARTBEAT-ACK", "cipher": "None"}'::jsonb,
                 'Enforce mTLS (mutual TLS) with X.509 client certificates and restrict subnet access via hardware security perimeter.',
                 'open'),
                (%s, %s, %s, 'Deprecated TLS 1.0 Negotiation Accepted on Clearing Service',
                 'settlement.switchcore.ng allows TLS 1.0 ciphers vulnerable to POODLE and BEAST downgrade attacks, failing CBN and PCI-DSS 4.0 mandates.',
                 'high', 'TLS / SSL',
                 '{"supported_protocols": ["TLSv1.0", "TLSv1.1", "TLSv1.2"], "weak_ciphers": ["TLS_RSA_WITH_3DES_EDE_CBC_SHA"]}'::jsonb,
                 'Disable TLS 1.0 and TLS 1.1 in reverse proxy configuration. Enforce TLS 1.3 with strict modern cipher suites.',
                 'open'),
                (%s, %s, %s, 'Missing Strict-Transport-Security Header on Public API Gateway',
                 'api.switchcore.ng does not return HSTS headers with long max-age and includeSubDomains.',
                 'medium', 'HTTP Security Headers',
                 '{"headers": {"Server": "uvicorn", "Content-Type": "application/json"}}'::jsonb,
                 'Add Strict-Transport-Security: max-age=63072000; includeSubDomains; preload to all HTTP response headers.',
                 'open'),
                (%s, %s, %s, 'Internal Network Topology Leakage via X-Forwarded-For',
                 'The telco USSD proxy leaks RFC1918 10.240.x.x internal subnet addressing in error response payloads.',
                 'low', 'Information Disclosure',
                 '{"internal_ip_detected": "10.240.18.91"}'::jsonb,
                 'Strip internal proxy headers before forwarding responses to clients.',
                 'open');
            """, (
                org2_id, switch_scan_id, switch_asset_ids[2],
                org2_id, switch_scan_id, switch_asset_ids[4],
                org2_id, switch_scan_id, switch_asset_ids[1],
                org2_id, switch_scan_id, switch_asset_ids[3],
            ))

            # SEED SCORE SNAPSHOTS FOR LAGOS CORE SWITCH
            cur.execute("""
                INSERT INTO score_snapshots (org_id, domain_id, score, subscores, factors, created_at)
                VALUES
                (%s, %s, 59, '{"tls": 52, "dns": 71, "headers": 54}'::jsonb, '["Critical ISO 8583 exposure", "TLS 1.0 on clearing"]'::jsonb, now() - interval '3 days'),
                (%s, %s, 62, '{"tls": 55, "dns": 74, "headers": 58}'::jsonb, '["Critical ISO 8583 exposure"]'::jsonb, now() - interval '1 day'),
                (%s, %s, 64, '{"tls": 58, "dns": 77, "headers": 61}'::jsonb, '["Critical ISO 8583 exposure", "HSTS missing"]'::jsonb, now());
            """, (org2_id, domain2_id, org2_id, domain2_id, org2_id, domain2_id))


            # =================================================================
            # SEED ASSETS FOR PANBANK AFRICA (org3)
            # =================================================================
            panbank_assets = [
                ('panbank.africa', '105.112.45.10', 'Corporate Portal', 'active', 200,
                 [{"name": "Next.js", "version": "14.2.3", "category": "Frontend Framework"}, {"name": "Cloudflare Enterprise", "category": "CDN / WAF"}],
                 {"issuer": "Cloudflare Inc ECC CA-3", "valid_to": "2027-01-15", "days_remaining": 118, "protocol": "TLSv1.3"},
                 {"A": ["105.112.45.10"], "MX": ["mx1.panbank.africa", "mx2.panbank.africa"], "TXT": ["v=spf1 include:_spf.panbank.africa -all"]}),
                ('ebanking.panbank.africa', '105.112.45.18', 'Retail Banking', 'active', 200,
                 [{"name": "Envoy", "version": "1.28.0", "category": "Edge Proxy"}, {"name": "React", "category": "UI"}, {"name": "Spring Cloud", "category": "Banking Gateway"}],
                 {"issuer": "DigiCert EV TLS CA G2", "valid_to": "2027-02-28", "days_remaining": 162, "protocol": "TLSv1.3"},
                 {"A": ["105.112.45.18"]}),
                ('swift-relay.panbank.africa', '105.112.45.24', 'Interbank Messaging', 'active', 403,
                 [{"name": "SWIFT Alliance Gateway", "version": "7.6", "category": "Financial Messaging"}, {"name": "mTLS Security Core", "category": "Security"}],
                 {"issuer": "SWIFT PKI Root", "valid_to": "2027-09-12", "days_remaining": 358, "protocol": "TLSv1.3"},
                 {"A": ["105.112.45.24"]}),
                ('mobile-api.panbank.africa', '105.112.45.32', 'Mobile Banking API', 'active', 200,
                 [{"name": "Kong Gateway Enterprise", "version": "3.5", "category": "API Gateway"}, {"name": "OAuth2 / OpenID Connect", "category": "Auth"}],
                 {"issuer": "DigiCert Secure Site Pro", "valid_to": "2026-12-30", "days_remaining": 102, "protocol": "TLSv1.3"},
                 {"A": ["105.112.45.32"]}),
                ('vault.panbank.africa', '105.112.45.40', 'Key Management Enclave', 'active', 403,
                 [{"name": "HashiCorp Vault Enterprise", "version": "1.16", "category": "HSM Enclave"}],
                 {"issuer": "Sovereign HSM CA", "valid_to": "2027-06-30", "days_remaining": 284, "protocol": "TLSv1.3"},
                 {"A": ["105.112.45.40"]}),
            ]
            panbank_asset_ids = []
            for host, ip, atype, status, hcode, techs, tls, dns in panbank_assets:
                cur.execute("""
                    INSERT INTO assets (org_id, domain_id, hostname, ip_address, asset_type, status, http_status, technologies, tls_info, dns_records)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                    RETURNING id;
                """, (org3_id, domain3_id, host, ip, atype, status, hcode, json.dumps(techs), json.dumps(tls), json.dumps(dns)))
                panbank_asset_ids.append(cur.fetchone()[0])

            # SEED SCAN FOR PANBANK AFRICA
            cur.execute("""
                INSERT INTO scans (org_id, domain_id, status, score, stage_progress, current_stage, started_at, completed_at)
                VALUES (%s, %s, 'completed', 88, '{
                    "discovery": {"status": "completed", "items": 5, "duration_ms": 1100},
                    "dns": {"status": "completed", "items": 5, "duration_ms": 780},
                    "http": {"status": "completed", "items": 5, "duration_ms": 1890},
                    "security_checks": {"status": "completed", "items": 22, "duration_ms": 3900},
                    "normalization": {"status": "completed", "items": 3, "duration_ms": 280},
                    "scoring": {"status": "completed", "score": 88, "duration_ms": 150}
                }'::jsonb, 'completed', now() - interval '5 hours', now() - interval '4 hours 52 minutes')
                RETURNING id;
            """, (org3_id, domain3_id))
            panbank_scan_id = cur.fetchone()[0]

            # SEED FINDINGS FOR PANBANK AFRICA (High score, minor hygiene findings)
            cur.execute("""
                INSERT INTO findings (org_id, scan_id, asset_id, title, description, severity, category, evidence, remediation, status)
                VALUES
                (%s, %s, %s, 'Permissive CORS Configuration on Public Mobile API',
                 'mobile-api.panbank.africa allows Access-Control-Allow-Origin: * on select telemetry routes.',
                 'medium', 'API Security',
                 '{"headers": {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Credentials": "true"}}'::jsonb,
                 'Specify explicit authorized mobile origin domains and reject wildcard origin in CORS headers.',
                 'open'),
                (%s, %s, %s, 'HSTS Max-Age Below 1 Year on Corporate Web Portal',
                 'The Strict-Transport-Security header specifies max-age=15552000 (180 days) instead of the recommended 2 years (63072000 seconds).',
                 'low', 'HTTP Security Headers',
                 '{"hsts_header": "max-age=15552000; includeSubDomains"}'::jsonb,
                 'Update Nginx or Cloudflare rule to enforce max-age=63072000 with preload directive.',
                 'open'),
                (%s, %s, %s, 'Server Banner Leaks Detailed Envoy Version',
                 'ebanking.panbank.africa includes server: envoy/1.28.0 in HTTP response headers.',
                 'info', 'Information Disclosure',
                 '{"server_header": "envoy/1.28.0"}'::jsonb,
                 'Configure server_tokens off in Envoy proxy configuration.',
                 'open');
            """, (
                org3_id, panbank_scan_id, panbank_asset_ids[3],
                org3_id, panbank_scan_id, panbank_asset_ids[0],
                org3_id, panbank_scan_id, panbank_asset_ids[1],
            ))

            # SEED SCORE SNAPSHOTS FOR PANBANK AFRICA
            cur.execute("""
                INSERT INTO score_snapshots (org_id, domain_id, score, subscores, factors, created_at)
                VALUES
                (%s, %s, 86, '{"tls": 90, "dns": 88, "headers": 81}'::jsonb, '["Minor CORS configuration"]'::jsonb, now() - interval '3 days'),
                (%s, %s, 88, '{"tls": 91, "dns": 89, "headers": 83}'::jsonb, '["Minor CORS configuration"]'::jsonb, now() - interval '1 day'),
                (%s, %s, 88, '{"tls": 92, "dns": 90, "headers": 84}'::jsonb, '["HSTS max-age recommendation"]'::jsonb, now());
            """, (org3_id, domain3_id, org3_id, domain3_id, org3_id, domain3_id))

            # =================================================================
            # SEED ASSETS FOR ACME AFRICA (org4)
            # =================================================================
            acme_assets = [
                ('acmetraders.ng', '102.134.88.12', 'Web Endpoint', 'active', 200,
                 [{"name": "Nginx", "version": "1.24.0", "category": "Web Server"}],
                 {"issuer": "Let's Encrypt", "valid_to": "2026-12-14", "days_remaining": 87, "protocol": "TLSv1.3"},
                 {"A": ["102.134.88.12"]}),
                ('api.acmetraders.ng', '102.134.88.14', 'API Gateway', 'active', 200,
                 [{"name": "FastAPI", "version": "0.115.0", "category": "Framework"}],
                 {"issuer": "Let's Encrypt", "valid_to": "2026-11-20", "days_remaining": 63, "protocol": "TLSv1.3"},
                 {"A": ["102.134.88.14"]}),
                ('auth.acmetraders.ng', '102.134.88.25', 'Web Endpoint', 'active', 200,
                 [{"name": "OAuth2 / OIDC", "category": "Identity Provider"}],
                 {"issuer": "Let's Encrypt", "valid_to": "2026-11-05", "days_remaining": 48, "protocol": "TLSv1.3"},
                 {"A": ["102.134.88.25"]}),
            ]
            acme_asset_ids = []
            for host, ip, atype, status, hcode, techs, tls, dns in acme_assets:
                cur.execute("""
                    INSERT INTO assets (org_id, domain_id, hostname, ip_address, asset_type, status, http_status, technologies, tls_info, dns_records)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                    RETURNING id;
                """, (org4_id, domain4_id, host, ip, atype, status, hcode, json.dumps(techs), json.dumps(tls), json.dumps(dns)))
                acme_asset_ids.append(cur.fetchone()[0])

            cur.execute("""
                INSERT INTO scans (org_id, domain_id, status, score, stage_progress, current_stage, started_at, completed_at)
                VALUES (%s, %s, 'completed', 73, '{"scoring": {"status": "completed", "score": 73}}'::jsonb, 'completed', now() - interval '1 day', now() - interval '23 hours')
                RETURNING id;
            """, (org4_id, domain4_id))
            acme_scan_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO findings (org_id, scan_id, asset_id, title, description, severity, category, evidence, remediation, status)
                VALUES
                (%s, %s, %s, 'Missing DNS SPF Record for Outbound Email Defense',
                 'Domain lacks SPF record allowing email spoofing.',
                 'medium', 'DNS Security',
                 '{"spf": "missing"}'::jsonb,
                 'Publish TXT record with SPF definition.',
                 'open');
            """, (org4_id, acme_scan_id, acme_asset_ids[0]))

            cur.execute("""
                INSERT INTO score_snapshots (org_id, domain_id, score, subscores, factors, created_at)
                VALUES (%s, %s, 73, '{"tls": 78, "dns": 65}'::jsonb, '["Missing SPF"]'::jsonb, now());
            """, (org4_id, domain4_id))

            conn.commit()
            print("Multi-tenant seeding completed successfully!")

if __name__ == "__main__":
    seed_tenants()
