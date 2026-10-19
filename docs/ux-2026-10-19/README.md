# UX overhaul of /comply and its neighbours (19 Oct 2026)

Same brand (tokens and components in `frontend/src/index.css`), clearer behaviour. Before and after screenshots (desktop 1440 and 390 wide)
are in `before/` and `after/` with the same file names (`<screen>-desktop.png`, `<screen>-mobile.png`). Screens that did not exist before
(for example `comply-incident-details`) have only an `after` image.

Regenerate either set with `OUT_DIR=../docs/ux-2026-10-19/after node scripts/capture-ux-screens.mjs` from `frontend/`. It serves the app against
fixtures and needs `/usr/bin/chromium`.

## What changed, by screen

| Screen | What changed |
|---|---|
| Compliance, all tabs | One dialog for every view and form-in-a-popup; plain-English labels and messages; empty / loading / error panels; a toast for every finished or failed action; tab bar with arrow-key support; 44px touch targets on phones; focus ring on every control. |
| Readiness | Tidied copy only (still "reference pending review"). Requirement detail stays an inline expander, not a popup. |
| Answer questions | Dates use the native date picker and show the organisation's zone. New renewal choice "A date I choose" (native date, sent as 23:59 that day in the organisation's zone, in UTC). |
| Incidents | Record and Edit are dialogs; Details is a read-only dialog (members too). Times use native date-time pickers in the organisation's zone, are sent as UTC, and a time the clocks skip or repeat is explained and never sent. Recording the Commission time asks first. |
| Packs | Details dialog (fingerprints, retention date, downloads). Issuing a pack asks first. |
| Documents | The document opens in a dialog; times now read in the organisation's zone, not UTC. Approving asks first. |
| Reports | Preview and Email are dialogs (a wide report scrolls inside the dialog). Dates in the organisation's zone. Shortening retention asks first. A failed load now shows an error with Try again (it used to look like "No reports yet"). |
| Domains | Add and How to verify are dialogs. Removing a domain, and removing a monitored host, ask first. A failed load shows an error with Try again. |
| Scans | Scan details and Start scan use the shared dialog (the side drawer is gone for scans). Copy tidied. |

## How to use the shared components

Import from these files only. All are small and documented at the top of each file.

### Dialog: `frontend/src/components/ui/Dialog.tsx`

```tsx
import Dialog, { useDialogClose } from '../components/ui/Dialog';

<Dialog open={!!viewing} onClose={() => setViewing(null)} title="Evidence file" maxWidth="max-w-2xl"
        dirty={formIsDirty}                       // optional: ask before throwing input away
        footer={<><CancelButton /><button type="submit" form="my-form">Save</button></>}>
  <form id="my-form">…</form>
</Dialog>

function CancelButton() { const close = useDialogClose(); return <button type="button" onClick={close}>Cancel</button>; }
```

- `components/Modal.tsx` still exists and is the same component, so old callers work. New code uses `ui/Dialog`.
- Render it only while it is needed (`{viewing && <Dialog open …>}`) or keep it mounted and pass `open`. Both work; focus returns to the opener either way.
- Mark the control that should start focused with `data-autofocus` (otherwise the first field is focused).
- The `footer` stays pinned at the bottom (on phones too). Put submit buttons there and link them with the `form` attribute.
- Do not add your own Esc, focus trap or scroll lock. Dialogs can stack (a confirmation over a form); only the top one reacts to keys.
- A dialog is full screen on phones. Use `compact` only for small confirmations.

### Confirmation: `frontend/src/components/ConfirmDialog.tsx` (re-exported by `ui/ConfirmDialog.tsx`)

```tsx
const confirm = useConfirm();
if (!(await confirm({
  title: 'Revoke access?',
  body: 'The reviewer will no longer be able to open your pack.',
  irreversible: 'A revoked link cannot be switched back on. You would need to invite them again.',
  confirmLabel: 'Revoke access',   // names the action. Never "OK".
  danger: true,                    // delete / remove / revoke: Cancel is the default focus
}))) return;
```

Use it for anything that cannot be undone: issuing, approving, recording a notification time, removing, deleting, revoking. Non-destructive confirmations
(issue, approve) leave focus on the confirm button.

### Dates and times: `frontend/src/lib/datetime.ts` and `frontend/src/components/ui/DateTimeField.tsx`

```tsx
const zone = useOrgZone();                       // lib/orgZone.ts: organisation's display zone, default Africa/Lagos
<DateTimeField label="Expires" zone={zone} value={wall} onChange={setWall} />            // datetime-local, zone shown beside it
<DateTimeField mode="date" label="Valid until" zone={zone} value={day} onChange={setDay} min={…} max={…} />

const r = localToUtc(wall, zone);                // { ok: true, utc: '2026-10-15T08:30:00.000Z' } or { ok: false, message }
if (!r.ok) return setError(r.message);            // a time the clocks skip or repeat: say so, never guess
api.save({ expires_at: r.utc });                  // always send UTC
```

- Never use a text box for a date or time. A day that is a calendar day (a date of birth, a report date) stays `YYYY-MM-DD`; a moment is sent as UTC.
- Show stored times with `utcToLocalInput(iso, zone)` (for a picker) or `fmtTimeZone` / `fmtDayZone` (for reading, in `pages/compliance/shared.tsx`).
- `npm run test:datetime` unit-tests the helper (clock changes, half-hour zones, round trips).

### States: `frontend/src/components/ui/StatePanels.tsx`

```tsx
if (error && !data) return <ErrorPanel title="We could not load your files" message={humanError(error, 'Something went wrong on our side. Try again in a moment.')} onRetry={load} />;
if (!data) return <LoadingPanel label="files" />;
if (rows.length === 0) return <EmptyPanel icon={<FileText size={26} />} title="No files yet" help="Add one file so a reviewer can see it." action={<button …>Add a file</button>} />;
```

`humanError(e, fallback)` never returns a status line or a server error for a 5xx; short plain 4xx messages from the API pass through.
The API helpers `listReports` and `getDomains` still return empty lists on failure (other pages rely on it); use the `…Strict` versions when you need an error state.

### Toasts: `useToast()` from `components/Toast.tsx`

One short sentence for every completed or failed action (`toast('Pack issued.')`, `toast('The pack was not issued. Try again in a moment.')`).
Toasts are drawn on `<body>`, above dialogs, and are announced to screen readers.

### Adding a tab to /comply

Append one entry to `TABS` in `frontend/src/pages/Compliance.tsx`: `{ key, label, render: ctx => <MyTab canEdit={ctx.canEdit} zone={ctx.zone} /> }`.
The tab bar (including arrow keys, Home and End) and the ARIA wiring come for free. Pass more through `TabContext` if you need it.

## Tests

- `npm run test:compliance-ui` — dialogs (focus in, trap, Esc, focus back, inert page, full screen on phones), confirmations for every irreversible action,
  native pickers sending UTC and clock-change messages, states, toasts, keyboard-only flow, 44px targets, focus ring, no overflow at 320/390/desktop, banned phrases.
- `npm run test:ux-ui` — the same for Reports and Domains.
- `npm run test:datetime` — the time-zone helper.
- `backend/tests/test_ux_copy_claims.py` — banned phrases in the source of every screen and shared component touched here.
  Add a new file to its `FILES` list when you add UI copy.
