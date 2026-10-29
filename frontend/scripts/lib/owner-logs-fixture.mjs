// Fixtures for the owner console logs view (docs/owner-logs-2026-10-29). Synthetic rows only: example.test
// addresses, made-up ids. The shape matches GET /api/v1/owner/logs for both sources.
export const ORG_ID = "0a000000-0000-4000-8000-000000000001";
export const ORG_NAME = "Acme Traders Ltd";

// A row whose details run past the visible cap, with one long unbroken value and a nested object.
const bigMetadata = {
  reason: "Customer asked by email, ticket 42",
  from_plan: "starter",
  to_plan: "growth",
  previous_period_end: "2026-11-20T00:00:00+00:00",
  new_period_end: "2026-12-20T00:00:00+00:00",
  request_path: "/api/v1/owner/organizations/0a000000-0000-4000-8000-000000000001/plan?source=console&confirm=typed-name-gate-with-a-very-long-query-string-value-that-has-no-spaces-at-all",
  filters: { q: "acme", billing: "paid", sort: "members", dir: "desc" },
  members_before: 4,
  members_after: 4,
  invoice_number: "INV-2026-00042",
  provider: "manual",
  note: "Plan changed while the customer was on a call with support. The new plan starts today and renews monthly.",
  session_hint: "console",
  tags: ["billing", "support", "plan"],
};

export const OWNER_ROWS = [
  { id: "7b1e0c52-1f0a-4c55-9d1e-000000000001", created_at: "2026-10-29T08:14:07.512Z", action: "owner.action.change_plan",
    outcome: "success", actor_email: "owner@example.test", actor_name: "Ada Owner", target_type: "organization",
    target_id: ORG_ID, org_id: ORG_ID, org_name: ORG_NAME, ip: "203.0.113.7", metadata: bigMetadata },
  { id: "7b1e0c52-1f0a-4c55-9d1e-000000000002", created_at: "2026-10-29T07:59:41.000Z", action: "owner.action.suspend",
    outcome: "rejected", actor_email: "owner@example.test", actor_name: "Ada Owner", target_type: "organization",
    target_id: ORG_ID, org_id: ORG_ID, org_name: ORG_NAME, ip: "203.0.113.7",
    metadata: { reason: "Repeated failed payments", detail: "The organization name you typed does not match." } },
  { id: "7b1e0c52-1f0a-4c55-9d1e-000000000003", created_at: "2026-10-29T07:40:00.000Z", action: "owner.sign_in",
    outcome: "denied", actor_email: "someone@example.test", actor_name: null, target_type: null, target_id: null,
    org_id: null, org_name: null, ip: "198.51.100.23", metadata: {} },
  { id: "7b1e0c52-1f0a-4c55-9d1e-000000000004", created_at: "2026-10-29T07:30:12.000Z", action: "owner.view.logs",
    outcome: "success", actor_email: "owner@example.test", actor_name: "Ada Owner", target_type: null, target_id: null,
    org_id: null, org_name: null, ip: "203.0.113.7", metadata: { source: "owner" } },
  // Few keys, one of them very long: the length cap applies, not the count cap.
  { id: "7b1e0c52-1f0a-4c55-9d1e-000000000005", created_at: "2026-10-29T07:10:00.000Z", action: "owner.export.organizations",
    outcome: "success", actor_email: "owner@example.test", actor_name: "Ada Owner", target_type: null, target_id: null,
    org_id: null, org_name: null, ip: "203.0.113.7",
    metadata: { rows: 120, truncated: false,
      hosts: Array.from({ length: 60 }, (_, i) => `host-${String(i + 1).padStart(2, "0")}.acme.example`) } },
];

export const CUSTOMER_ROWS = [
  { id: "5c2d9e10-7a3b-4f61-8c2e-000000000001", created_at: "2026-10-29T06:05:00.000Z", action: "scan.launched",
    resource_type: "scan", resource_id: "9f8e7d6c-0000-4000-8000-00000000abcd", metadata: { domain: "acme.example", scan_type: "EXTERNAL_ASSESSMENT" },
    org_id: ORG_ID, org_name: ORG_NAME, user_id: "u1", user_email: "c1@example.test", user_name: "Chidi Okafor" },
  { id: "5c2d9e10-7a3b-4f61-8c2e-000000000002", created_at: "2026-10-28T18:22:00.000Z", action: "member.invited",
    resource_type: "invite", resource_id: "inv-1", metadata: { role: "member", invited_email: "new.person@example.test" },
    org_id: ORG_ID, org_name: ORG_NAME, user_id: "u1", user_email: "c1@example.test", user_name: "Chidi Okafor" },
  { id: "5c2d9e10-7a3b-4f61-8c2e-000000000003", created_at: "2026-10-28T09:00:00.000Z", action: "auth.sign_in",
    resource_type: null, resource_id: null, metadata: {}, org_id: null, org_name: null,
    user_id: "u2", user_email: "ops@kola.example", user_name: null },
];

/** Answers GET /api/v1/owner/logs like the API: filtered by source, newest first. */
export function logsPayload(url) {
  const source = url.searchParams.get("source") === "owner" ? "owner" : "customer";
  return { source, items: source === "owner" ? OWNER_ROWS : CUSTOMER_ROWS, limit: 100, offset: 0 };
}
