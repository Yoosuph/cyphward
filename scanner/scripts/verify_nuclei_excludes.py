"""Fail the build unless the pinned templates still match the committed exclusion policy.

Rebuilds the exclusion set from the installed templates and compares it, byte for
byte, to scanner/nuclei_policy/exclude_ids.txt. A template change that would add an
intrusive or credential/form-submitting template, or drop one, makes the hashes
differ and stops the image build.

Usage: python verify_nuclei_excludes.py <templates_dir> <policy_dir>
"""
import hashlib, json, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_nuclei_excludes as builder

templates_dir, policy_dir = sys.argv[1], pathlib.Path(sys.argv[2])
committed = (policy_dir / "exclude_ids.txt").read_text()
committed_policy = json.loads((policy_dir / "policy.json").read_text())

with tempfile.TemporaryDirectory() as tmp:
    try:
        builder.main(templates_dir, tmp)
    except SystemExit as exc:
        if exc.code:
            print("verify: templates still contain credential/form submitters not in the policy", file=sys.stderr)
            raise
    rebuilt = (pathlib.Path(tmp) / "exclude_ids.txt").read_text()
    rebuilt_policy = json.loads((pathlib.Path(tmp) / "policy.json").read_text())

if hashlib.sha256(rebuilt.encode()).hexdigest() != hashlib.sha256(committed.encode()).hexdigest():
    added = sorted(set(rebuilt.split()) - set(committed.split()))
    removed = sorted(set(committed.split()) - set(rebuilt.split()))
    print(f"verify: exclusion list drift. +{len(added)} -{len(removed)}. "
          f"Regenerate with build_nuclei_excludes.py and review.", file=sys.stderr)
    print("added (first 10):", added[:10], file=sys.stderr)
    sys.exit(1)
assert rebuilt_policy["remaining_that_submit_credentials_or_forms"] == 0
print(f"verify: ok, {committed_policy['excluded']} templates excluded, 0 remaining submit credentials/forms")
