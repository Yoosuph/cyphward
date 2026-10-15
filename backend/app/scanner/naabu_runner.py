"""
Cyphward Naabu Port Discovery Runner
Runs ProjectDiscovery naabu (connect mode, top-N TCP ports) against hosts.
Falls back gracefully if the naabu binary is not installed.
"""
import asyncio
from shared.scan_budget import gather_with_deadline, ensure_stage_budget
import json
import logging
import shutil
from typing import Any, Dict, List

from backend.app.scanner import ip_guard
from backend.app.scanner.tool_results import ToolExecutionError, collect_tool_results

logger = logging.getLogger("cyphward.scanner.naabu")


async def run_naabu(
    hostname: str,
    top_ports: int = 100,
    timeout: int = 60,
    rate: int = 500,
    strict: bool = False,
) -> List[Dict[str, Any]]:
    """
    Scan top TCP ports on a single host using connect mode (no raw sockets,
    works unprivileged). Returns normalized open_port observations.
    """
    # SSRF boundary: only ever connect to an approved public IP — by IP, so
    # the target cannot rebind between validation and connect.
    target_ip = await asyncio.to_thread(ip_guard.resolve_connect_ip, hostname)
    if not target_ip:
        if strict:
            raise ToolExecutionError("Naabu target is unresolved or not a public address")
        logger.info("naabu skip %s: unresolved or non-public address", hostname)
        return []

    naabu_path = shutil.which("naabu")
    if not naabu_path:
        if strict:
            raise ToolExecutionError("Naabu is not installed")
        return []

    cmd = [
        naabu_path,
        "-host", target_ip,
        "-top-ports", str(top_ports),
        "-scan-type", "CONNECT",
        "-rate", str(rate),
        "-silent",
        "-json",
        "-disable-update-check",
    ]

    findings: List[Dict[str, Any]] = []
    proc = None
    try:
        ensure_stage_budget()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            err = (stderr or b"").decode(errors="replace").strip()[:300]
            logger.warning("naabu %s exited %s: %s", hostname, proc.returncode, err)
            raise ToolExecutionError(f"Naabu exited with code {proc.returncode}")

        seen_ports = set()
        for line in stdout.decode(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                if strict:
                    raise ToolExecutionError("Naabu returned malformed JSON output")
                continue
            port = data.get("port")
            if not port:
                continue
            port = int(port)
            if port in seen_ports:
                continue
            seen_ports.add(port)
            findings.append({
                "hostname": hostname,
                "ip": data.get("ip"),
                "port": port,
                "protocol": data.get("protocol") or "tcp",
            })
    except asyncio.TimeoutError:
        logger.warning("naabu %s timed out after %ss", hostname, timeout)
        if strict:
            raise ToolExecutionError(f"Naabu timed out after {timeout}s")
    except Exception as e:
        logger.warning("naabu %s failed: %s", hostname, e)
        if strict:
            raise ToolExecutionError(str(e)) from e
    finally:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

    return findings


async def run_naabu_batch(
    hostnames: List[str],
    top_ports: int = 100,
    timeout: int = 60,
    concurrency: int = 4,
) -> List[Dict[str, Any]]:
    """Run naabu across hosts with bounded concurrency. One stage at a time (§16)."""
    hostnames = list(dict.fromkeys(hostnames))
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(host: str) -> List[Dict[str, Any]]:
        async with semaphore:
            return await run_naabu(host, top_ports=top_ports, timeout=timeout, strict=True)

    results = await gather_with_deadline([_one(h) for h in hostnames])

    return collect_tool_results(hostnames, results)
