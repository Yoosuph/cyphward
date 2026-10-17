"""Every scanner HTTP request identifies Cyphward with a URL explaining the scanner."""
import asyncio
import json
import pathlib
import re

import httpx

from backend.app.scanner import ip_guard, nuclei_runner, privacy_probe
from shared.scanner_identity import SCANNER_INFO_URL, SCANNER_USER_AGENT

SCANNER_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "scanner"


def test_the_user_agent_names_cyphward_and_links_the_explanation():
    assert SCANNER_USER_AGENT == "Cyphward-Security-Scanner/1.0 (+https://cyphward.com/scanner)"
    assert SCANNER_INFO_URL in SCANNER_USER_AGENT


def test_no_scanner_module_sets_its_own_user_agent():
    offenders = []
    for path in SCANNER_DIR.glob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"User-Agent", line, re.I) and "SCANNER_USER_AGENT" not in line and not line.strip().startswith("#"):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, offenders


def test_privacy_fetches_send_the_user_agent(monkeypatch):
    monkeypatch.setattr(ip_guard, "resolve_connect_ip", lambda host: "93.184.216.34")
    seen = []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, text="<html><title>x</title></html>")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await privacy_probe.fetch_in_scope(client, "https://acme.example.test/", ["acme.example.test"])
    asyncio.run(run())
    assert seen == [SCANNER_USER_AGENT]


def test_nuclei_is_told_to_send_the_user_agent(monkeypatch):
    captured = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

        async def wait(self):
            return 0

    async def fake_exec(*cmd, **kwargs):
        captured.append(list(cmd))
        return Proc()

    monkeypatch.setattr(nuclei_runner.ip_guard, "resolve_connect_ip", lambda host: "93.184.216.34")
    monkeypatch.setattr(nuclei_runner.shutil, "which", lambda name: "/usr/bin/nuclei")
    monkeypatch.setattr(nuclei_runner.asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(nuclei_runner.run_nuclei("acme.example.test"))
    asyncio.run(nuclei_runner.run_nuclei_template("acme.example.test", "some-template"))
    assert len(captured) == 2
    for cmd in captured:
        i = cmd.index("-H")
        assert cmd[i + 1] == f"User-Agent: {SCANNER_USER_AGENT}"


def test_the_public_scanner_page_shows_the_same_user_agent():
    page = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "Scanner.tsx").read_text()
    assert f"'{SCANNER_USER_AGENT}'" in page, "update frontend/src/pages/Scanner.tsx with the new User-Agent"


# ── Nuclei safe-scan policy ────────────────────────────────────────────────
from backend.app.scanner import nuclei_runner


def test_nuclei_excludes_the_intrusive_tags_and_rate_limits():
    args = nuclei_runner._nuclei_safety_args()
    assert "-rate-limit" in args and args[args.index("-rate-limit") + 1] == "10"
    tags = args[args.index("-exclude-tags") + 1].split(",")
    for t in ("default-login", "brute-force", "bruteforce", "intrusive", "fuzz", "fuzzing", "dos"):
        assert t in tags
    assert "-exclude-id" in args, "the credential/form exclusion list must be passed"


def test_the_committed_policy_excludes_credential_and_form_submitters_leaving_none():
    policy = nuclei_runner.nuclei_policy()
    assert policy["available"] and policy["templates_version"] == "v10.4.9"
    assert policy["remaining_that_submit_credentials_or_forms"] == 0
    assert policy["excluded_by_reason"]["submits_credentials_or_form"] > 0


def test_excluded_template_ids_are_actually_in_the_list():
    ids = set(pathlib.Path(nuclei_runner.nuclei_policy()["exclude_ids_path"]).read_text().split())
    # A default-login and a credential/form submitter from v10.4.9 (by tag and by body).
    assert "3Com-wireless-default-login" in ids
    assert len(ids) == nuclei_runner.nuclei_policy()["excluded"]


def test_a_tampered_exclusion_list_fails_closed(monkeypatch, tmp_path):
    (tmp_path / "exclude_ids.txt").write_text("only-one-id\n")
    (tmp_path / "policy.json").write_text(json.dumps({"exclude_ids_sha256": "deadbeef", "excluded": 1}))
    monkeypatch.setattr(nuclei_runner, "NUCLEI_POLICY_DIR", tmp_path)
    nuclei_runner.nuclei_policy.cache_clear()
    import pytest
    with pytest.raises(nuclei_runner.ToolExecutionError):
        nuclei_runner.nuclei_policy()
    nuclei_runner.nuclei_policy.cache_clear()


def test_both_nuclei_invocations_pass_the_safety_args(monkeypatch):
    captured = []

    class Proc:
        returncode = 0
        async def communicate(self): return b"", b""
        async def wait(self): return 0

    async def fake_exec(*cmd, **kwargs):
        captured.append(list(cmd)); return Proc()

    monkeypatch.setattr(nuclei_runner.ip_guard, "resolve_connect_ip", lambda host: "93.184.216.34")
    monkeypatch.setattr(nuclei_runner.shutil, "which", lambda name: "/usr/bin/nuclei")
    monkeypatch.setattr(nuclei_runner.asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(nuclei_runner.run_nuclei("acme.example.test"))
    asyncio.run(nuclei_runner.run_nuclei_template("acme.example.test", "some-id"))
    assert len(captured) == 2
    for cmd in captured:
        assert "-exclude-tags" in cmd and "-exclude-id" in cmd
        assert cmd[cmd.index("-rate-limit") + 1] == "10"
        assert "-H" in cmd
