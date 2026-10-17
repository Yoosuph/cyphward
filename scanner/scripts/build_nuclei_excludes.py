"""Build the Nuclei safe-scan exclusion policy for a pinned nuclei-templates version.

Excludes every http/ template that is intrusive by tag, or that actively submits
credentials or a form (as a request, not merely a response matcher). The output
is a committed ID list the scanner passes to `nuclei -exclude-id`, plus a policy
summary recorded in scan evidence. Deterministic for a given templates version.

Usage: python build_nuclei_excludes.py <templates_dir> <out_dir>
"""
import collections, hashlib, json, pathlib, re, sys
import yaml

EXCLUDE_TAGS = ["default-login", "brute-force", "bruteforce", "intrusive", "fuzz", "fuzzing", "dos"]
# Directories whose purpose is credential submission or fuzzing.
EXCLUDE_DIRS = ("http/default-logins/", "http/credential-stuffing/", "http/token-spray/", "http/fuzzing/")
CRED_FIELD = re.compile(r"(?:^|[^A-Za-z])(pass(?:word|wd)?|j_password|login|user(?:name)?|email)\s*[=:]", re.I)
CRED_TEMPLATE_VAR = re.compile(r"\{\{\s*(?:username|password|user|pass|email|login)\s*\}\}", re.I)
FORM_CT = re.compile(r"content-type:\s*(?:application/x-www-form-urlencoded|multipart/form-data)", re.I)
BASIC_AUTH = re.compile(r"authorization:\s*basic\s", re.I)
WRITE_METHODS = {"POST", "PUT", "PATCH"}


def request_blocks(template):
    """Only the request side of each http block: method, raw requests, headers, body, payloads."""
    for block in (template.get("http") or template.get("requests") or []):
        if not isinstance(block, dict):
            continue
        yield block


def submits_credentials_or_form(template):
    for block in request_blocks(template):
        method = str(block.get("method") or "").upper()
        raws = block.get("raw") or []
        raw_text = "\n".join(r for r in raws if isinstance(r, str))
        body = block.get("body")
        body_text = body if isinstance(body, str) else json.dumps(body) if body is not None else ""
        headers = block.get("headers") or {}
        header_text = json.dumps(headers)
        has_payloads = bool(block.get("payloads")) and bool(block.get("attack"))
        # A login form / credential POST, basic-auth submission, or payload fuzzing.
        if BASIC_AUTH.search(header_text) or BASIC_AUTH.search(raw_text):
            return True
        if raw_text and (CRED_FIELD.search(raw_text) or CRED_TEMPLATE_VAR.search(raw_text) or FORM_CT.search(raw_text)) \
                and re.search(r"^(POST|PUT|PATCH)\s", raw_text, re.M):
            return True
        if method in WRITE_METHODS and (CRED_FIELD.search(body_text) or CRED_TEMPLATE_VAR.search(body_text)
                                        or FORM_CT.search(header_text)):
            return True
        if has_payloads and (CRED_FIELD.search(body_text + raw_text) or CRED_TEMPLATE_VAR.search(body_text + raw_text)):
            return True
    return False


def main(templates_dir, out_dir):
    root = pathlib.Path(templates_dir)
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    excluded_ids, reasons = {}, collections.Counter()
    total = kept = 0
    remaining_credential = []
    for path in sorted(root.glob("http/**/*.yaml")):
        rel = str(path.relative_to(root))
        try:
            t = yaml.safe_load(path.read_text(errors="replace")) or {}
        except Exception:
            continue
        tid = t.get("id")
        if not tid:
            continue
        total += 1
        info = t.get("info") or {}
        tags = {x.strip().lower() for x in str(info.get("tags") or "").split(",") if x.strip()}
        reason = None
        if tags & set(EXCLUDE_TAGS):
            reason = "tag"
        elif rel.startswith(EXCLUDE_DIRS):
            reason = "directory"
        elif submits_credentials_or_form(t):
            reason = "submits_credentials_or_form"
        if reason:
            excluded_ids[tid] = reason
            reasons[reason] += 1
        else:
            kept += 1
            if submits_credentials_or_form(t):  # must be zero by construction
                remaining_credential.append(tid)
    ids_sorted = sorted(excluded_ids)
    ids_text = "\n".join(ids_sorted) + "\n"
    ids_sha = hashlib.sha256(ids_text.encode()).hexdigest()
    (out / "exclude_ids.txt").write_text(ids_text)
    policy = {
        "templates_version": "v10.4.9",
        "exclude_tags": EXCLUDE_TAGS,
        "total_http_templates": total,
        "excluded": len(excluded_ids),
        "excluded_by_reason": dict(reasons),
        "kept": kept,
        "remaining_that_submit_credentials_or_forms": len(remaining_credential),
        "exclude_ids_sha256": ids_sha,
    }
    (out / "policy.json").write_text(json.dumps(policy, indent=2) + "\n")
    print(json.dumps(policy, indent=2))
    if remaining_credential:
        print("REMAINING (not excluded but flagged):", remaining_credential[:20], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
