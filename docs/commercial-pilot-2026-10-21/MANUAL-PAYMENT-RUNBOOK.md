# Confirmed manual payments: operator procedure

No payment gateway is activated. No bank transfer is initiated by this code. A workspace owner cannot activate/renew a paid period through the customer API or by changing the company profile. An open invoice never proves collection.

## Before use

1. Apply `supabase/migrations/20261021090000_manual_payment_reference.sql` before the new operator script. It adds a unique index only for new paid receipts prefixed `manual-confirmed:`; existing invoices, periods and history are untouched. Check for unexpected duplicate prefixed references before applying; investigate rather than deleting records to make the index pass.
2. Deploy API changes before the updated marketing and Settings pages. Otherwise the old API can still self-activate while the new page promises manual confirmation. Rollback must retain the API restrictions and receipt index; disable new UI rather than restoring self-service activation.
3. Privately review existing active/no-subscription legacy records. This code preserves them for compatibility; it cannot prove whether previous transfers were received. Do not count them as paid without reconciliation. Future work to remove legacy exemptions needs an explicit migration/customer communication plan.
   Honor existing written commercial agreements and committed periods. Updated public wording describes the existing 30-day implementation; it does not authorize retrospectively changing a customer's contract.
4. Use an authorized operator environment and an explicit database destination from the secret store. Never put a connection URL in a document, command output or Git. The script ignores ordinary `DATABASE_URL` and .env files.

The script is an operator tool protected by database credentials, not a customer endpoint or a substitute for console MFA. It requires attribution to a currently listed platform owner. An operator with database credentials can already change this data; protect and restrict those credentials accordingly.

## Confirm and preview

Verify the incoming transaction in the business's bank statement. Match the customer, amount, currency, unique bank reference and agreed service period. A screenshot supplied by a customer or an unpaid invoice is insufficient confirmation. Keep bank evidence in the private finance system, not Git or audit free text.

Standard prices accepted by this tool: Starter `1500000` kobo (₦15,000), Growth `2500000` kobo (₦25,000), one 30-day period. Custom/partial payments, refunds, credits and mid-period tier changes need separate reconciliation; do not alter the amount to fit the script or label a partial payment as fully paid.

Set `CYPHWARD_MANUAL_BILLING_DATABASE_URL` privately. Prepare `CYPHWARD_PAYMENT_ORG_ID`, `CYPHWARD_PAYMENT_ACTOR_ID` (a named platform owner), `CYPHWARD_PAYMENT_REFERENCE` and `CYPHWARD_PAYMENT_REASON` from the actual reconciliation. For local rehearsal, use only a loopback `cyphward_test` or `cyphward_demo` database. The default command is a dry run:

```bash
python -m backend.scripts.record_manual_payment \
  --org-id "$CYPHWARD_PAYMENT_ORG_ID" \
  --actor-id "$CYPHWARD_PAYMENT_ACTOR_ID" \
  --plan growth --amount-kobo 2500000 \
  --reference "$CYPHWARD_PAYMENT_REFERENCE" \
  --reason "$CYPHWARD_PAYMENT_REASON"
```

Production requires both `--target production --confirm-production RECORD-CONFIRMED-PAYMENT`, including for a dry run. Check the displayed organization ID, plan, amount, currency and dates against the agreement. Then repeat the same reviewed command with `--apply --confirm-payment-received` only after the transfer is independently confirmed. No production invocation was performed while creating this change.

## Effect and idempotency

- New/trial/expired accounts: the paid period begins when recorded and lasts 30 days. An unused trial ends; confirm that with the customer before applying.
- An unexpired active subscription on the **same** plan: a new confirmed transfer adds 30 days to the existing end. Remaining paid time is retained.
- An active paid subscription on a **different** plan: refused. Agree remaining time/credit before recording a change; this tool does not prorate.
- One transaction creates a new paid invoice, sets the subscription active, updates the plan and records owner/customer audit events. Audit failure rolls everything back. Old open invoices remain open; do not count the new receipt plus an older invoice as two sales. Review and void obsolete invoices through a separately authorized operator procedure.
- References are normalized to uppercase. Repeating the same reference with the same organization, plan and amount returns the existing invoice and cannot add another period. A reused reference with different details is refused. Reference/organization locks plus the unique index protect concurrent submissions.
- A database error or lost connection is an uncertain result, not proof of success or failure. Re-run the exact same reference and details; inspect the returned receipt and subscription, rather than entering a new reference.

Verify invoice status/amount, paid end date, effective entitlements and both audit events privately after recording. Tell the customer their actual end date. Do not automatically email them or run a scan as part of reconciliation. At renewal, collect and confirm a new transfer under a new genuine reference.

## Expiry and customer access

Existing accepted jobs may finish; expiry does not rewrite their history. New scans/reports/domain additions/member invitations have zero allowance for an expired/canceled subscription. Existing views and privacy exports use existing permissions. Growth-only evidence/file views retain the existing Starter-fallback restrictions after expiry; arrange retrieval before expiry where needed and do not promise indefinite full Growth access.

Authorized platform owners can explicitly extend a trial using the existing audited console action (bounded by its current limits); a customer cannot restart it by switching plans. Neither extension nor a plan change is revenue. Never silently convert unverified legacy periods into payment receipts.

## Safe rehearsal and release evidence

Run the new manual-payment PostgreSQL tests with explicit owned `cyphward_test` application/admin URLs. They cover dry runs, exact/case-normalized replay, concurrent duplicate receipts, amount/actor validation, preservation of paid time, database uniqueness and audit rollback. Run admission, plan and billing regressions alongside them. Test public and Settings views with mocked APIs on desktop/390/320px.

Record actual passing counts, migration count, revision and deployment state in [VALIDATION.md](VALIDATION.md). Preserve the primary/fork publication rule. Scanner source edits in this change can trigger scanner CD on a main merge; review deployment-path filters and coordinate the release rather than merging as if it were only marketing copy.
