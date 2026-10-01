"""
Cyphward Passive Subdomain Discovery Worker
Gathers attack surface assets passively using:
1. crt.sh (Certificate Transparency logs)
2. HackerTarget passive host intelligence
3. Subfinder CLI (if present)
4. Curated sovereign subdomain permutation probing
"""
import shutil
import subprocess
import asyncio
import re
from typing import List, Set
import httpx


async def run_subfinder_async(domain: str) -> Set[str]:
    """Run subfinder asynchronously if installed in system path."""
    subdomains = set()
    subfinder_path = shutil.which("subfinder")
    if not subfinder_path:
        return subdomains

    try:
        cmd = [subfinder_path, "-d", domain, "-silent", "-timeout", "20"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
        for line in stdout.decode(errors="replace").splitlines():
            line = line.strip().lower()
            if line.endswith(domain):
                subdomains.add(line)
    except Exception:
        pass
    return subdomains

COMMON_SUBDOMAINS = [
    "www", "api", "mail", "app", "admin", "dev", "portal", "vpn",
    "auth", "secure", "cdn", "gateway", "staging", "test", "demo",
    "internal", "mx", "ns1", "ns2", "git", "status", "dashboard"
]


async def query_crt_sh(domain: str) -> Set[str]:
    """Query Certificate Transparency logs via crt.sh."""
    subdomains = set()
    try:
        url = f"https://crt.sh/?q=%.{domain}&output=json"
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Cyphward-Security-Scanner/1.0"})
            if resp.status_code == 200:
                data = resp.json()
                for entry in data:
                    name_value = entry.get("name_value", "")
                    for name in name_value.split("\n"):
                        name = name.strip().lower()
                        # Exclude wildcards
                        if name.startswith("*."):
                            name = name[2:]
                        if name.endswith(domain) and " " not in name and len(name) < 120:
                            subdomains.add(name)
    except Exception:
        pass
    return subdomains


async def query_hackertarget(domain: str) -> Set[str]:
    """Query HackerTarget passive hostsearch API."""
    subdomains = set()
    try:
        url = f"https://api.hackertarget.com/hostsearch/?q={domain}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Cyphward-Security-Scanner/1.0"})
            if resp.status_code == 200 and not resp.text.startswith("error"):
                for line in resp.text.splitlines():
                    parts = line.split(",")
                    if parts:
                        sub = parts[0].strip().lower()
                        if sub.endswith(domain):
                            subdomains.add(sub)
    except Exception:
        pass
    return subdomains





async def discover_subdomains(domain: str) -> List[str]:
    """
    Perform passive subdomain discovery for target domain.
    Aggregates results from multiple passive sources.
    Always includes the apex domain itself.
    """
    domain = domain.strip().lower()
    discovered: Set[str] = {domain}

    # Run all passive queries concurrently
    crt_task = asyncio.create_task(query_crt_sh(domain))
    ht_task = asyncio.create_task(query_hackertarget(domain))
    sf_task = asyncio.create_task(run_subfinder_async(domain))

    results = await asyncio.gather(crt_task, ht_task, sf_task, return_exceptions=True)
    for res in results:
        if isinstance(res, set):
            discovered.update(res)

    # Passive sources only — never invent hostnames. A fabricated wordlist
    # (www/api/auth/vpn/…) previously appeared here as a "fallback" when
    # crt.sh was down, which produced phantom assets for every real domain.
    # If discovery found nothing beyond the apex, that IS the answer.

    # Return sorted list
    return sorted(list(discovered))
