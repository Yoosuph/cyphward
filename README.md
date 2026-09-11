# CYPHWARD — Cyber Defense, Layer by Layer

An investor-demo-quality frontend for an AI-powered African cybersecurity &
compliance SaaS. React + TypeScript, **mock data only** — no backend, no real
API calls, no auth server. Visual system: **STRATA** (warm paper / ink /
oxide-red hairline design, Fraunces + Space Grotesk + IBM Plex Mono, light &
dark themes, command palette, live ticker).

## Stack

Vite · React 18 · TypeScript · Tailwind CSS · react-router-dom · lucide-react · recharts

## Quick start

Requires Node 18+.

```bash
npm install
npm run dev
```

Then open the URL Vite prints (usually `http://localhost:5173`).

## Demo flow

1. **Login** (`/login`) — any email/password signs you in (mock, ~400ms).
2. You land on the **Dashboard** (`/`): 742/1000 score ring, sub-scores,
   compliance 14/18, training 92%, live threat ticker.
3. Sidebar routes (all live): `/comply`, `/detect`, `/score`, `/academy`, `/copilot`.
4. Press **⌘K / Ctrl·K** anywhere for the command palette.
5. Theme toggle (sun/moon) switches the STRATA paper/ink themes.

## Scripts

| Command           | What it does                    |
| ----------------- | ------------------------------- |
| `npm run dev`     | Start the dev server            |
| `npm run build`   | Type-check and build for prod   |
| `npm run preview` | Preview the production build    |

## Structure

```
src/
  main.tsx, App.tsx        # entry, router + shell
  index.css                # STRATA design tokens + component styles
  data/mock.ts             # ALL mock data in one module
  lib/api.ts               # async wrappers over mock (TODO markers for real endpoints)
  lib/auth.tsx, theme.ts, hooks.ts, format.ts
  components/              # Sidebar, Topbar, ScoreRing, DataTable, ThreatTicker, …
  pages/                   # Login, Dashboard, Comply, Detect, Score, Academy, Copilot
```

All numbers and labels come from `src/data/mock.ts`. To go real, replace the
bodies of the functions in `src/lib/api.ts` — the pages never touch mock data
directly.
