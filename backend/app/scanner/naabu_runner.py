"""
Cyphward Naabu Port Discovery Runner
Runs ProjectDiscovery naabu (connect mode, top-N TCP ports) against hosts.
Falls back gracefully if the naabu binary is not installed.
"""
import asyncio
import json
import logging
import shutil
from typing import Any, Dict, List

logger = logging.getLogger("cyphward.scanner.naabu")


async def run_naabu(
    hostname: str,
    top_ports: int = 100,
    timeout: int = 60,
    rate: int = 500,
) -> List[Dict[str, Any]]:
    """
    Scan top TCP ports on a single host using connect mode (no raw sockets,
    works unprivileged). Returns normalized open_port observations.
    """
    naabu_path = shutil.which("naabu")
    if not naabu_path:
        return []

    cmd = [
        naabu_path,
        "-host", hostname,
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
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode not in (0, None):
            err = (stderr or b"").decode(errors="replace").strip()[:300]
            logger.warning("naabu %s exited %s: %s", hostname, proc.returncode, err)

        seen_ports = set()
        for line in stdout.decode(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
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
    except Exception as e:
        logger.warning("naabu %s failed: %s", hostname, e)
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
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(host: str) -> List[Dict[str, Any]]:
        async with semaphore:
            return await run_naabu(host, top_ports=top_ports, timeout=timeout)

    results = await asyncio.gather(*[_one(h) for h in hostnames], return_exceptions=True)

    all_findings: List[Dict[str, Any]] = []
    for idx, result in enumerate(results):
        if isinstance(result, list):
            host = hostnames[idx] if idx < len(hostnames) else ""
            for f in result:
                if not f.get("hostname"):
                    f["hostname"] = host
            all_findings.extend(result)
    return all_findings
