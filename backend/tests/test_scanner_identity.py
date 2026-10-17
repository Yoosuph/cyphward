"""Every scanner HTTP request identifies Cyphward with a URL explaining the scanner."""
import asyncio
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
