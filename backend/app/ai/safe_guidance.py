"""Curated configuration guides: models cannot replace rollout prerequisites."""
import re


def configuration_topic(text):
    text = str(text or "").lower()
    if re.search(r"\b(dmarc|spf|dkim|spoof\w*|email)\b", text):
        return "email"
    if re.search(r"\b(hsts|tls|ssl|cipher\w*)\b|strict-transport-security", text):
        return "transport"
    if re.search(r"\bcsp\b|content-security-policy|frame-ancestors|clickjacking|x-frame-options", text):
        return "browser_policy"
    return None


def curated_chat(message, history=()):
    if configuration_topic(message) or re.search(r"\b(ndpa|compliance|cbn|law|board|briefing|executive|report)\b", message, re.I):
        return True
    # Follow-up code requests must not escape the preceding guide's safeguards.
    return any(configuration_topic(h.get("content", "")) for h in history[-6:] if h.get("role") == "user")


def configuration_guide(finding, stack="nginx"):
    title = finding.get("title") or "Recorded finding"
    topic = configuration_topic(title)
    if topic is None:
        return None
    if "dmarc" in title.lower():
        steps = [
            "Inventory all legitimate sending services and configure aligned SPF/DKIM with their providers.",
            "Start a new DMARC rollout in monitoring mode (p=none). Do not reduce an existing enforcement policy without a separate reason and review.",
            "Configure a real reporting mailbox/service before adding rua. Review reports over normal sending cycles, including infrequent senders, and fix legitimate authentication failures.",
            "Only then increase enforcement gradually to quarantine and reject, testing delivery and keeping a rollback plan. Immediate reject can block legitimate messages.",
            "A DNS recheck confirms a record; it cannot establish that mail delivers or that all impersonation is prevented.",
        ]
        example = "# Monitoring example for a NEW rollout; confirm the domain and reporting setup first.\n# Host: _dmarc.<your-verified-domain>\nv=DMARC1; p=none"
        source = "https://support.google.com/a/answer/10032473"
    elif topic == "email":
        steps = [
            "Inventory every legitimate sending service and obtain each provider's documented SPF/DKIM configuration.",
            "Keep one SPF record and account for its DNS lookup limit. Never copy another organization's include value or invent a reporting mailbox.",
            "Test authentication and alignment for each legitimate mail stream before tightening the all qualifier. Receiving systems determine delivery; -all is not a delivery guarantee.",
            "Confirm the domain's actual mail use before applying a no-senders policy. DNS evidence alone does not prove delivery.",
        ]
        example = "# No universal SPF value: use the documented configuration for YOUR actual sending providers."
        source = "https://support.google.com/a/answer/33786"
    elif "certificate" in title.lower():
        steps = [
            "Confirm the recorded certificate hostname, issuer, validity dates and the exact listener/load balancer that presented it.",
            "Use that service's certificate provider to renew or replace the affected certificate and install the complete chain for the correct hostnames. Keep private keys private.",
            "Test the new certificate and affected clients in staging, then use the service's documented reload/deployment procedure with a rollback plan.",
            "Check the certificate actually served from each affected endpoint and configure renewal monitoring. A DNS or HSTS change does not repair an expired certificate.",
        ]
        example = "# Use the actual certificate provider and serving endpoint; no universal renewal command."
        source = "https://letsencrypt.org/docs/"
    elif topic == "transport":
        steps = [
            "Review the actual certificate/protocol/header evidence; this guide does not establish that HSTS is missing or a TLS version is enabled.",
            "Confirm valid HTTPS on the host, test affected clients in staging, and prepare a rollback plan before changing transport settings.",
            "For a new HSTS rollout, start with a short max-age and test before increasing it. Do not reset an existing policy just to match an example.",
            "Inventory every subdomain before includeSubDomains; HTTP-only subdomains can become inaccessible. Preload submission needs a separate review and has a removal delay.",
            "Use your actual server/CDN documentation. Recheck the header and exercise real client connections after changes.",
        ]
        example = "# Choose HSTS max-age for the reviewed rollout.\n# Do not enable includeSubDomains or preload until their prerequisites are confirmed."
        source = "https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Strict-Transport-Security"
    else:
        steps = [
            "Inventory required scripts, styles, connections and legitimate embedded pages with the application owner.",
            "Trial an application-specific CSP with Content-Security-Policy-Report-Only; configure reporting deliberately and review violations before enforcement.",
            "Test sign-in, payments, third-party integrations and allowed embeds in staging; choose explicit allowed origins and nonces/hashes that fit the application.",
            "Review frame-ancestors or X-Frame-Options separately. A blanket DENY can break legitimate partner embeds.",
            "Enforce only after validation with a rollback plan; the presence of a header does not establish that the application is free of vulnerabilities.",
        ]
        example = "# Build an application-specific policy in report-only mode first.\n# There is no universally safe production allowlist."
        source = "https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP"
    return {
        "finding_id": finding.get("id"), "title": title, "target_stack": stack,
        "summary": f"Staged configuration review for {title}. Confirm provider-specific settings before production changes.",
        "prerequisites": ["Authorized access to the relevant configuration", "An inventory of legitimate senders or application dependencies", "A staging test and rollback plan"],
        "steps": steps + [f"Reference: {source}"], "code_snippet": example,
        "verification_command": "Review the recorded evidence and use the supported finding recheck after testing the actual service.",
        "estimated_time_minutes": None,
    }
