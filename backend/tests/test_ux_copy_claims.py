"""The UX overhaul's copy never states a verdict (docs/ux-2026-10-19).

The strings live in the frontend, so this reads the source of the screens and shared components the overhaul
touched and refuses the full list of banned phrases. The browser suites check the rendered text too; this catches
copy that is only shown in a state the suites do not reach.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "frontend" / "src"

BANNED = (
    "compliant", "certified", "certification", "satisfies", "satisfied", "passes audit", "pass the audit",
    "compliance score", "fully meets", "meets the requirement", "is met", "partial compliance", "fully compliant",
    "is compliant", "satisfy ndpa", "adequate", "adequacy", "guarantee",
)

FILES = (
    "pages/Compliance.tsx",
    "pages/compliance/Documents.tsx",
    "pages/compliance/Incidents.tsx",
    "pages/compliance/Packs.tsx",
    "pages/compliance/Questionnaire.tsx",
    "pages/compliance/shared.tsx",
    "pages/Reports.tsx",
    "pages/Scans.tsx",
    "pages/Domains.tsx",
    "components/Toast.tsx",
    "components/ConfirmDialog.tsx",
    "components/ui/Dialog.tsx",
    "components/ui/ConfirmDialog.tsx",
    "components/ui/DateTimeField.tsx",
    "components/ui/StatePanels.tsx",
    "lib/datetime.ts",
)


def test_files_exist():
    missing = [f for f in FILES if not (ROOT / f).is_file()]
    assert not missing, f"update the list: {missing}"


def test_overhaul_copy_has_no_banned_phrases():
    hits = []
    for name in FILES:
        text = (ROOT / name).read_text(encoding="utf-8").lower()
        for phrase in BANNED:
            if phrase in text:
                hits.append(f"{name}: {phrase}")
    assert not hits, "verdict language in UI copy: " + "; ".join(hits)
