"""
Cyphward Nuclei Integration Runner
Executes ProjectDiscovery Nuclei templates against discovered hosts for deep vulnerability detection.
Falls back gracefully if Nuclei binary is not installed.
"""
import asyncio
import json
import shutil
from typing import List, Dict, Any


SEVERITY_MAP = {
    "info": "info",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "critical",
}


async def run_nuclei(
    hostname: str,
    templates: str = "http/",
    severity: str = "low,medium,high,critical",
    timeout: int = 300,
    rate_limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Run Nuclei against a hostname and return normalized findings.
    Requires: nuclei binary in PATH (go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest)
    """
    nuclei_path = shutil.which("nuclei")
    if not nuclei_path:
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
        "-rate-limit", str(rate_limit),
        "-no-color",
        "-disable-update-check",
    ]

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        for line in stdout.decode(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            info = data.get("info", {})
            matched_at = data.get("matched-at") or data.get("matched", hostname)
            template_id = data.get("template-id") or data.get("templateID", "")
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

    except asyncio.TimeoutError:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
    except Exception:
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
    concurrency: int = 10,
    timeout: int = 300,
) -> List[Dict[str, Any]]:
    """Run Nuclei across multiple hosts concurrently."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_with_semaphore(host: str) -> List[Dict[str, Any]]:
        async with semaphore:
            return await run_nuclei(host, templates, severity, timeout)

    tasks = [_run_with_semaphore(h) for h in hostnames]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_findings = []
    for idx, result in enumerate(results):
        if isinstance(result, list):
            host = hostnames[idx] if idx < len(hostnames) else ""
            for finding in result:
                if not finding.get("_hostname"):
                    finding["_hostname"] = host
            all_findings.extend(result)

    return all_findings
