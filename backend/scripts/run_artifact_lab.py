"""Start only the local report lab, optionally reusing an existing AI key file.

Reads ONLY GEMINI_API_KEY/GEMINI_MODEL from --ai-env; never imports database,
scanner, mail, session or other production configuration. Prints no secrets.
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

root = Path(__file__).resolve().parents[2]
load_dotenv(root / ".env", override=True)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ai-env", type=Path)
parser.add_argument("--model", default=os.getenv("CYPHWARD_ARTIFACT_MODEL", "gemini-2.5-flash"))
args = parser.parse_args()
if args.ai_env:
    values = dotenv_values(args.ai_env)
    for name in ("GEMINI_API_KEY", "GEMINI_MODEL"):
        if values.get(name):
            os.environ[name] = values[name]
os.environ["GEMINI_MODEL"] = args.model
os.environ["CYPHWARD_ARTIFACT_AI"] = "live"
# Fail closed to accidental production/local-server configuration changes.
from backend.app.ai.report_artifacts import enabled
if not enabled():
    raise SystemExit("Refusing: the artifact lab needs development mode and a local database.")
if not os.getenv("GEMINI_API_KEY"):
    raise SystemExit("Provide GEMINI_API_KEY or --ai-env to run the live AI experiment.")
print(f"Starting local artifact lab with live Gemini ({os.getenv('GEMINI_MODEL', 'gemini-2.5-flash-lite')}); local database retained.", flush=True)
os.chdir(root)
os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"])
