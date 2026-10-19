"""Report (and optionally delete) evidence-file objects that nothing points at.

  python backend/scripts/reconcile_evidence_files.py            # read-only report (default)
  python backend/scripts/reconcile_evidence_files.py --delete   # also delete the orphans listed

Needs DATABASE_URL, SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment (nothing is read from a file other
than backend/.env, which the app already loads). Orphans are storage objects with no database row (an organisation
that was deleted, an upload whose row failed) and objects whose row is marked removed (a delete that failed).
Objects younger than --min-age seconds with no row are left alone: an upload may be between its put and its insert.
The report holds object paths and counts only: no file names, no contents, no keys.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import storage as file_storage  # noqa: E402
from backend.app.compliance import evidence_file_store  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delete", action="store_true", help="delete the orphans (default: report only)")
    parser.add_argument("--min-age", type=int, default=evidence_file_store.RECONCILE_MIN_AGE_SECONDS,
                        help="seconds an object with no row must have existed before it is judged an orphan")
    parser.add_argument("--check-bucket", action="store_true", help="also check that the bucket exists and is private")
    args = parser.parse_args(argv)
    try:
        storage = file_storage.get_storage()
    except file_storage.StorageNotConfigured as exc:
        print(f"error: {exc} Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.", file=sys.stderr)
        return 2
    code = 0
    if args.check_bucket:
        private = storage.bucket_is_private() if hasattr(storage, "bucket_is_private") else None
        print(f"bucket {file_storage.BUCKET}: " + {True: "private", False: "PUBLIC", None: "missing"}[private])
        if private is not True:
            code = 1
    report = evidence_file_store.reconcile(storage, delete=args.delete, min_age_seconds=args.min_age)
    print(json.dumps({"mode": "delete" if args.delete else "report-only", **report}, indent=2))
    return code or (1 if (report["failed"] or (report["orphans"] or report["removed_but_present"]) and not args.delete) else 0)


if __name__ == "__main__":
    raise SystemExit(main())
