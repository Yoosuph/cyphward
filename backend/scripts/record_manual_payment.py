"""Operator-only reconciliation of an independently confirmed bank transfer.

Dry-run by default. No .env loading, inherited DATABASE_URL, payment-network
call or customer HTTP endpoint. The operator supplies the exact database and
attributes the receipt to a named platform owner. See the pilot runbook.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
from uuid import UUID

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from backend.app.billing.provider import PLAN_PRICES_KOBO


def validate_destination(url, target, confirmation=None):
    if not url:
        raise ValueError("Supply --database-url or CYPHWARD_MANUAL_BILLING_DATABASE_URL explicitly.")
    info = conninfo_to_dict(url)
    local = info.get("host") in {"127.0.0.1", "localhost", "::1"} and info.get("dbname") in {"cyphward_test", "cyphward_demo"}
    if target == "local" and not local:
        raise ValueError("Local mode requires loopback cyphward_test or cyphward_demo.")
    if target == "production" and confirmation != "RECORD-CONFIRMED-PAYMENT":
        raise ValueError("Production needs --confirm-production RECORD-CONFIRMED-PAYMENT.")


def record_payment(conn, *, org_id, actor_id, plan, reference, amount_kobo, reason, apply=False):
    org_id, actor_id = str(UUID(org_id)), str(UUID(actor_id))
    if plan not in PLAN_PRICES_KOBO or amount_kobo != PLAN_PRICES_KOBO[plan]:
        raise ValueError("Amount must match the selected plan's current NGN price in kobo; custom terms need separate review.")
    reference = reference.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._:/-]{5,119}", reference):
        raise ValueError("Use the bank's unique transaction reference (6–120 letters, digits or ._:/-).")
    if not 5 <= len(reason.strip()) <= 500:
        raise ValueError("A reconciliation reason of 5–500 characters is required.")
    ref = "manual-confirmed:" + reference
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SET LOCAL statement_timeout = '15s'")
            # Serialize reference replay across different organizations, then use
            # the same organization lock as admission and owner plan changes.
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (ref,))
            cur.execute("SELECT user_id FROM platform_owners WHERE user_id = %s", (actor_id,))
            if not cur.fetchone():
                raise ValueError("The recorded actor must be a named platform owner.")
            cur.execute("SELECT id FROM organizations WHERE id = %s FOR UPDATE", (org_id,))
            if not cur.fetchone():
                raise ValueError("Organization not found.")
            cur.execute("SELECT id, org_id, plan, amount_kobo, currency, period_end FROM invoices WHERE provider_ref = %s AND status = 'paid'", (ref,))
            prior = cur.fetchone()
            if prior:
                if (str(prior["org_id"]), prior["plan"], prior["amount_kobo"], prior["currency"]) != (org_id, plan, amount_kobo, "NGN"):
                    raise ValueError("That transfer reference was already used for different payment details.")
                return {"state": "already_recorded", "invoice_id": str(prior["id"]), "period_end": prior["period_end"].isoformat()}
            cur.execute("SELECT * FROM subscriptions WHERE org_id = %s FOR UPDATE", (org_id,))
            sub = cur.fetchone()
            now = datetime.now(timezone.utc)
            live_paid = bool(sub and sub["status"] == "active" and sub["current_period_end"] > now)
            if live_paid and sub["plan"] != plan:
                raise ValueError("A different paid plan is still active. Agree its end/credit before recording a new plan.")
            start = sub["current_period_end"] if live_paid else now
            end = start + timedelta(days=30)
            if not apply:
                return {"state": "dry_run", "org_id": org_id, "plan": plan, "amount_kobo": amount_kobo,
                        "currency": "NGN", "period_start": start.isoformat(), "period_end": end.isoformat()}
            cur.execute(
                "INSERT INTO invoices (org_id, plan, amount_kobo, currency, status, provider_ref, period_start, period_end) "
                "VALUES (%s,%s,%s,'NGN','paid',%s,%s,%s) RETURNING id",
                (org_id, plan, amount_kobo, ref, start, end))
            invoice_id = str(cur.fetchone()["id"])
            cur.execute(
                "INSERT INTO subscriptions (org_id, plan, status, provider, current_period_start, current_period_end, trial_ends_at) "
                "VALUES (%s,%s,'active','manual',%s,%s,NULL) ON CONFLICT (org_id) DO UPDATE SET "
                "plan=EXCLUDED.plan, status='active', provider='manual', current_period_start=EXCLUDED.current_period_start, "
                "current_period_end=EXCLUDED.current_period_end, trial_ends_at=NULL, cancel_at_period_end=false, updated_at=now()",
                (org_id, plan, sub["current_period_start"] if live_paid else start, end))
            cur.execute("UPDATE organizations SET plan=%s, updated_at=now() WHERE id=%s", (plan, org_id))
            metadata = {"reason": reason.strip(), "invoice_id": invoice_id, "plan": plan,
                        "amount_kobo": amount_kobo, "currency": "NGN", "period_end": end.isoformat(), "channel": "operator_reconciliation"}
            cur.execute(
                "INSERT INTO owner_audit (actor_user_id, action, outcome, target_type, target_id, metadata) "
                "VALUES (%s,'owner.payment_confirmed','success','organization',%s,%s::jsonb)",
                (actor_id, org_id, json.dumps(metadata)))
            cur.execute(
                "INSERT INTO audit_log (org_id, action, resource_type, resource_id, metadata) "
                "VALUES (%s,'billing.payment_confirmed','invoice',%s,%s::jsonb)",
                (org_id, invoice_id, json.dumps({"by": "cyphward", "plan": plan, "period_end": end.isoformat()})))
            return {"state": "recorded", "invoice_id": invoice_id, "period_end": end.isoformat()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("CYPHWARD_MANUAL_BILLING_DATABASE_URL"))
    parser.add_argument("--target", choices=("local", "production"), default="local")
    parser.add_argument("--confirm-production")
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--plan", choices=tuple(PLAN_PRICES_KOBO), required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--amount-kobo", type=int, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-payment-received", action="store_true")
    args = parser.parse_args(argv)
    try:
        validate_destination(args.database_url, args.target, args.confirm_production)
        if args.apply and not args.confirm_payment_received:
            raise ValueError("Reconcile the bank statement first, then add --confirm-payment-received.")
        with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
            result = record_payment(conn, org_id=args.org_id, actor_id=args.actor_id, plan=args.plan,
                                    reference=args.reference, amount_kobo=args.amount_kobo, reason=args.reason, apply=args.apply)
        print(json.dumps(result))
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    except psycopg.Error:
        # Database exception strings can contain connection credentials.
        parser.exit(2, "Database operation failed; inspect private operator logs. No receipt is confirmed by this output.\n")


if __name__ == "__main__":
    main()
