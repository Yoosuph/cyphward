-- New confirmed bank-transfer receipts are idempotent across organizations.
-- Existing invoice/period/history values are untouched. Apply before the
-- operator reconciliation script; this does not enable a payment provider.
CREATE UNIQUE INDEX IF NOT EXISTS invoices_confirmed_manual_reference_key
ON invoices (provider_ref)
WHERE status = 'paid' AND provider_ref LIKE 'manual-confirmed:%';
