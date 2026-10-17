"""
Cyphward Nuclei Integration Runner
Executes ProjectDiscovery Nuclei templates against discovered hosts for deep vulnerability detection.
Falls back gracefully if Nuclei binary is not installed.
"""
import asyncio
from shared.scan_budget import gather_with_deadline, ensure_stage_budget
from shared.scanner_identity import SCANNER_USER_AGENT
import json
import os
import functools
import hashlib
import pathlib
import shutil
import re
from datetime import datetime, timezone
from typing import List, Dict, Any

from backend.app.scanner import ip_guard
from backend.app.scanner.tool_results import ToolExecutionError, collect_tool_results


NUCLEI_POLICY_DIR = pathlib.Path(__file__).resolve().parents[3] / "scanner" / "nuclei_policy"
NUCLEI_EXCLUDE_TAGS = "default-login,brute-force,bruteforce,intrusive,fuzz,fuzzing,dos"
# ~10 requests/second per host and one template at a time keeps scans gentle.
NUCLEI_RATE_LIMIT = int(os.getenv("SCANNER_NUCLEI_RATE_LIMIT", "10"))


@functools.lru_cache(maxsize=1)
def nuclei_policy():
    """The committed exclusion policy (ids file, version, hash), loaded once. Fails closed on tamper."""
    ids_file = NUCLEI_POLICY_DIR / "exclude_ids.txt"
    policy_file = NUCLEI_POLICY_DIR / "policy.json"
    if not ids_file.exists() or not policy_file.exists():
        return {"available": False}
    meta = json.loads(policy_file.read_text())
    observed = hashlib.sha256(ids_file.read_text().encode()).hexdigest()
    if observed != meta.get("exclude_ids_sha256"):
        raise ToolExecutionError("Nuclei exclusion list hash mismatch; refusing to scan")
    meta.update(available=True, exclude_ids_path=str(ids_file))
    return meta


def _nuclei_safety_args():
    args = ["-exclude-tags", NUCLEI_EXCLUDE_TAGS, "-rate-limit", str(NUCLEI_RATE_LIMIT)]
    policy = nuclei_policy()
    if policy.get("available"):
        args += ["-exclude-id", policy["exclude_ids_path"]]
    return args


SEVERITY_MAP = {
    "info": "info",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "critical",
}


async def _nuclei_version() -> str | None:
    """Best-effort bounded identity lookup; failure never fabricates a version."""
    binary = shutil.which("nuclei")
    if not binary:
        return None
    proc = None
    try:
        ensure_stage_budget()
        proc = await asyncio.create_subprocess_exec(
            binary, "-version", stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=_nuclei_environment())
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=2)
        if proc.returncode != 0:
            return None
        match = re.search(r"(?:Nuclei Engine Version:|Current Version:)\s*v?(\d+\.\d+\.\d+(?:[-+][\w.-]+)?)",
                          (stdout + stderr).decode(errors="replace"), re.IGNORECASE)
        return match.group(1) if match else None
    except Exception:
        return None
    finally:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass


def _nuclei_resource_args() -> List[str]:
    """Bound concurrency inside each CLI process, separately from host batches."""
    def setting(name: str, default: int) -> str:
        value = int(os.getenv(name, str(default)))
        if not 1 <= value <= 64:
            raise ValueError(f"{name} must be between 1 and 64")
        return str(value)

    return [
        "-concurrency", setting("SCANNER_NUCLEI_TEMPLATE_CONCURRENCY", 4),
        "-bulk-size", "1",
        "-payload-concurrency", setting("SCANNER_NUCLEI_PAYLOAD_CONCURRENCY", 1),
        "-js-concurrency", setting("SCANNER_NUCLEI_JS_CONCURRENCY", 1),
        "-template-loading-concurrency", setting("SCANNER_NUCLEI_LOADING_CONCURRENCY", 1),
        "-probe-concurrency", "1",
        "-scan-strategy", "host-spray",
    ]


def _nuclei_environment() -> Dict[str, str]:
    # The scanner's Core key and application/database credentials are not
    # needed by a target-scanning subprocess. Keep its environment minimal.
    allowed = {
        "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "TZ", "SYSTEMROOT",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "LD_LIBRARY_PATH",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env["GOMEMLIMIT"] = os.getenv("SCANNER_NUCLEI_GOMEMLIMIT", "384MiB")
    env["GOGC"] = os.getenv("SCANNER_NUCLEI_GOGC", "50")
    env["GOMAXPROCS"] = os.getenv("SCANNER_NUCLEI_GOMAXPROCS", "1")
    return env


def _nuclei_exit_error(code: int) -> str:
    if code == -9:
        return "Nuclei was killed (SIGKILL); check worker/container memory limits"
    return f"Nuclei exited with code {code}"


def _parse_nuclei_stdout(stdout: bytes, hostname: str, strict: bool = False) -> List[Dict[str, Any]]:
    """Decode Nuclei JSONL output into normalized finding dicts."""
    findings: List[Dict[str, Any]] = []
    for line in stdout.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            if strict:
                raise ToolExecutionError("Nuclei returned malformed JSON output")
            continue

        if not isinstance(data, dict) or not isinstance(data.get("info"), dict):
            if strict:
                raise ToolExecutionError("Nuclei returned an invalid finding record")
            continue

        if data.get("error"):
            if strict:
                raise ToolExecutionError("Nuclei reported a request or template error")
            continue
        if "matcher-status" in data and type(data["matcher-status"]) is not bool:
            if strict:
                raise ToolExecutionError("Nuclei returned an invalid matcher status")
            continue
        if data.get("matcher-status") is False:
            # A failed matcher event is not a vulnerability or a full-template
            # completion receipt. It cannot establish a clean assessment.
            continue

        info = data.get("info", {})
        matched_at = data.get("matched-at") or data.get("matched", hostname)
        template_id = data.get("template-id") or data.get("templateID", "")
        if not isinstance(template_id, str) or not template_id.strip():
            if strict:
                raise ToolExecutionError("Nuclei finding has no template identity")
            continue
        sev = SEVERITY_MAP.get(info.get("severity", "").lower(), "medium")

        findings.append({
            "_hostname": hostname,
            "title": info.get("name", f"Nuclei: {template_id}"),
            "description": info.get("description", f"Nuclei template {template_id} matched on {hostname}"),
            "severity": sev,
            "category": "Nuclei Scan",
            "evidence": {
                "template_id": template_id,
                "matched_at": matched_at,
                "matcher_name": data.get("matcher-name", ""),
                "type": data.get("type", "http"),
                "host": hostname,
                "tags": info.get("tags", []),
                "reference": info.get("reference", []),
                "classification": info.get("classification", {}),
                "curl_command": data.get("curl-command", ""),
            },
            "remediation": info.get("remediation", f"Review {template_id} finding on {hostname} and apply vendor-recommended patches."),
        })
    return findings


async def run_nuclei_template(
    hostname: str,
    template_id: str,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    Rerun a single Nuclei template against a host — used by remediation
    verification to re-check the exact rule that produced a finding.

    Returns {"ok": bool, "findings": [...], "error": str|None}. ok=False
    means the rerun produced no usable proof either way (binary missing,
    crash, timeout) and the caller must treat verification as inconclusive.
    """
    # SSRF boundary: nuclei connects by name (vhost/Host header matter), so
    # validate the resolution first and refuse non-public targets.
    if not await asyncio.to_thread(ip_guard.resolve_connect_ip, hostname):
        return {
            "ok": False,
            "findings": [],
            "error": f"refused: {hostname} resolves only to non-public addresses",
        }

    nuclei_path = shutil.which("nuclei")
    if not nuclei_path:
        return {"ok": False, "findings": [], "error": "nuclei is not installed"}

    cmd = [
        nuclei_path,
        "-u", f"https://{hostname}",
        "-id", template_id,
        "-severity", "info,low,medium,high,critical",
        "-jsonl",
        "-silent",
        "-timeout", "10",
        "-retries", "1",
        "-no-color",
        "-disable-update-check",
        "-H", f"User-Agent: {SCANNER_USER_AGENT}",
        *_nuclei_safety_args(),
        *_nuclei_resource_args(),
    ]

    proc = None
    try:
        ensure_stage_budget()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_nuclei_environment(),
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
        return {"ok": False, "findings": [], "error": f"rerun timed out after {timeout}s"}
    except Exception as exc:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
        return {"ok": False, "findings": [], "error": str(exc)[:300]}
    finally:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

    rc = proc.returncode if proc.returncode is not None else -1
    # A non-zero process exit is not proof that a finding is fixed.
    if rc != 0:
        return {"ok": False, "findings": [], "error": _nuclei_exit_error(rc)}

    try:
        findings = _parse_nuclei_stdout(stdout, hostname, strict=True)
    except ToolExecutionError as error:
        return {"ok": False, "findings": [], "error": str(error)}
    if not any((finding.get("evidence") or {}).get("template_id") == template_id for finding in findings):
        return {"ok": False, "findings": findings,
                "error": "No matching finding was returned, but per-template completion was not proven."}
    return {"ok": True, "findings": findings, "error": None}


async def run_nuclei(
    hostname: str,
    templates: str = "http/",
    severity: str = "low,medium,high,critical",
    timeout: int = 300,
    rate_limit: int = NUCLEI_RATE_LIMIT,
    strict: bool = False,
) -> List[Dict[str, Any]]:
    """
    Run Nuclei against a hostname and return normalized findings.
    Requires: nuclei binary in PATH (go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest)
    """
    # SSRF boundary: validate resolution before handing the name to nuclei
    # (it needs the hostname for SNI/Host; redirects stay off by default).
    if not await asyncio.to_thread(ip_guard.resolve_connect_ip, hostname):
        if strict:
            raise ToolExecutionError("Nuclei target is unresolved or not a public address")
        return []

    nuclei_path = shutil.which("nuclei")
    if not nuclei_path:
        if strict:
            raise ToolExecutionError("Nuclei is not installed")
        return []

    findings = []
    cmd = [
        nuclei_path,
        "-u", f"https://{hostname}",
        "-t", templates,
        "-severity", severity,
        "-jsonl",
        "-silent",
        "-timeout", "10",
        "-retries", "1",
        "-no-color",
        "-disable-update-check",
        "-H", f"User-Agent: {SCANNER_USER_AGENT}",
        *_nuclei_safety_args(),
        *_nuclei_resource_args(),
    ]

    proc = None
    try:
        ensure_stage_budget()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_nuclei_environment(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            raise ToolExecutionError(_nuclei_exit_error(proc.returncode))
        findings = _parse_nuclei_stdout(stdout, hostname, strict=True)

    except asyncio.TimeoutError:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
        if strict:
            raise ToolExecutionError(f"Nuclei timed out after {timeout}s")
    except Exception as error:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
        if strict:
            raise ToolExecutionError(str(error)) from error
    finally:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

    return findings


async def run_nuclei_batch(
    hostnames: List[str],
    templates: str = "http/",
    severity: str = "low,medium,high,critical",
    concurrency: int = 1,
    timeout: int = 300,
) -> List[Dict[str, Any]]:
    """Run Nuclei across multiple hosts concurrently."""
    hostnames = list(dict.fromkeys(hostnames))
    started_at = datetime.now(timezone.utc).isoformat()
    version = await _nuclei_version() if hostnames else None
    max_processes = max(1, min(4, int(os.getenv("SCANNER_NUCLEI_MAX_PROCESSES", "1"))))
    semaphore = asyncio.Semaphore(max(1, min(concurrency, max_processes)))

    async def _run_with_semaphore(host: str) -> List[Dict[str, Any]]:
        async with semaphore:
            return await run_nuclei(host, templates, severity, timeout, strict=True)

    tasks = [_run_with_semaphore(h) for h in hostnames]
    results = await gather_with_deadline(tasks)

    batch = collect_tool_results(hostnames, results)
    # CLI exit success and match JSONL do not attest that every selected
    # template ran for a host. Preserve that gap explicitly, including legacy
    # installations whose engine/template version cannot be observed.
    batch.tool_coverage = {
        "version": 1, "tool": "nuclei", "tool_version": version,
        "requested_selector": templates, "severity_filter": severity,
        "template_set_version": nuclei_policy().get("templates_version"), "evaluated_templates": None,
        "negative_verification": "unknown",
        "safety_policy": {"rate_limit_per_second": NUCLEI_RATE_LIMIT, "exclude_tags": NUCLEI_EXCLUDE_TAGS,
                          "excluded_templates": nuclei_policy().get("excluded"),
                          "exclude_ids_sha256": nuclei_policy().get("exclude_ids_sha256")},
        "started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat(),
        "per_host_timeout_seconds": timeout,
        "targets": {host: {
            "process_status": "completed" if host in batch.successful_hosts else
                              "incomplete" if batch.failed_hosts.get(host) == "recon_stage_deadline" else "failed",
            "matched_templates": sorted({str((finding.get("evidence") or {}).get("template_id"))
                                          for finding in batch if finding.get("_hostname") == host
                                          and (finding.get("evidence") or {}).get("template_id")}),
            "evaluation_status": "unknown",
        } for host in hostnames},
    }
    return batch
