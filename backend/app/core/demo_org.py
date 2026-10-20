"""Identity of the sample-data demo organisation ("Fintech Org (SAMPLE DATA)").

backend/scripts/seed_fintech_demo.py writes it and removes it. Production metrics leave it out by these ids
(owner console overview). Nothing else in the app treats it specially: it is an ordinary organisation whose
domain is pending, so the app never scans it and never grades it at organisation level.
"""

DEMO_ORG_ID = "f1ac0000-0000-4000-8000-000000000001"
DEMO_USER_ID = "f1ac0000-0000-4000-8000-000000000002"
