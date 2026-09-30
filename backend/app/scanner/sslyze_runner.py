"""
Cyphward SSLyze TLS Analysis Runner
Extracts certificate details, supported TLS versions, and accepted cipher
suites for HTTPS services. Falls back gracefully if sslyze is not installed.
Emits raw observations only — risk decisions belong to Core (§19/§20).
"""
import asyncio
import json
import shutil
import tempfile
from typing import Any, Dict, List, Optional

# Scan commands: certificate + modern/relevant protocol versions.
_SSLYZE_ARGS = [
    "--certificate",
    "--tls_1_3",
    "--tls_1_2",
    "--tls_1_1",
    "--tls_1",
]

_TLS_VERSION_KEYS = {
    "tls_1_3": "tls_1_3_cipher_suites",
    "tls_1_2": "tls_1_2_cipher_suites",
    "tls_1_1": "tls_1_1_cipher_suites",
    "tls_1_0": "tls_1_cipher_suites",
}


def _parse_sslyze_json(raw: Dict[str, Any], hostname: str, port: int) -> Dict[str, Any]:
    """Defensively extract certificate + cipher observations from sslyze JSON."""
    observation: Dict[str, Any] = {"hostname": hostname, "port": port}

    # --- certificate ---
    cert_info: Optional[Dict[str, Any]] = None
    try:
        deployments = (
            raw.get("certificates", {})
            .get("result", {})
            .get("certificate_deployments", [])
        )
        if deployments:
            chain = deployments[0].get("received_certificate_chain", [])
            if chain:
                leaf = chain[0]
                cert_info = {
                    "subject": leaf.get("subject"),
                    "issuer": leaf.get("issuer"),
                    "not_valid_before": str(leaf.get("not_valid_before")) if leaf.get("not_valid_before") else None,
                    "not_valid_after": str(leaf.get("not_valid_after")) if leaf.get("not_valid_after") else None,
                    "subject_alternative_names": leaf.get("subject_alternative_names") or [],
                    "hostname_validation": deployments[0].get("hostname_validation_result"),
                    "is_leaf_certificate_chain": deployments[0].get("leaf_certificate_subject"),
                }
                # Sanitize accidental object values
                for k, v in list(cert_info.items()):
                    if v is not None and not isinstance(v, (str, int, float, bool, list)):
                        cert_info[k] = str(v)
    except Exception:
        cert_info = None
    observation["certificate"] = cert_info

    # --- TLS versions + accepted ciphers ---
    tls_versions: Dict[str, Any] = {}
    accepted_ciphers: List[str] = []
    for version, key in _TLS_VERSION_KEYS.items():
        node = raw.get(key)
        if not isinstance(node, dict):
            continue
        result = node.get("result") or {}
        accepted = result.get("accepted_cipher_suites") or []
        rejected = result.get("rejected_cipher_suites") or []
        tls_versions[version] = {
            "accepted_cipher_count": len(accepted),
            "rejected_cipher_count": len(rejected),
            "supported": len(accepted) > 0,
        }
        for suite in accepted:
            name = suite.get("cipher_suite", {}).get("name") if isinstance(suite, dict) else None
            if name:
                accepted_ciphers.append(name)
    observation["tls_versions"] = tls_versions
    observation["accepted_cipher_suites"] = accepted_ciphers[:50]
    return observation


async def run_sslyze(
    hostname: str,
    port: int = 443,
    timeout: int = 60,
) -> Optional[Dict[str, Any]]:
    """
    Run sslyze against host:port. Returns a normalized TLS observation, or
    None on failure/absence (stage degrades, scan continues).
    """
    sslyze_path = shutil.which("sslyze")
    if not sslyze_path:
        return None

    with tempfile.NamedTemporaryFile(mode="r", suffix=".json", delete=False) as tmp:
        out_path = tmp.name

    cmd = [sslyze_path, f"{hostname}:{port}", f"--json_out_file={out_path}", *_SSLYZE_ARGS]

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        with open(out_path, "r") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return None
        return _parse_sslyze_json(raw, hostname, port)
    except asyncio.TimeoutError:
        return None
    except Exception:
        # sslyze exits non-zero on some TLS failures but may still write JSON;
        # any parse/execution error degrades the stage without failing the scan.
        return None
    finally:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
        try:
            import os
            os.unlink(out_path)
        except OSError:
            pass


async def run_sslyze_batch(
    hostnames: List[str],
    port: int = 443,
    timeout: int = 60,
    concurrency: int = 2,
) -> List[Dict[str, Any]]:
    """Run sslyze against many hosts, sequentially-bounded (§16/§17)."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(host: str) -> Optional[Dict[str, Any]]:
        async with semaphore:
            return await run_sslyze(host, port=port, timeout=timeout)

    results = await asyncio.gather(*[_one(h) for h in hostnames], return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]
