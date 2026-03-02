# AeroCell Frontend

Student-facing Next.js 15 application for battery SOH analytics, recommendation guidance,
and explainable learning interactions.

## Commands

```powershell
npm install
npm run snapshots
npm run dev
npm run build
npm run test:e2e
npm run test:e2e:full
```

## Snapshot Pipeline

Builds typed mock JSON from parquet sources:

- `../data/event_manifest.parquet`
- `../data/event_timeseries.parquet`

Output files are created in `public/mock/` and consumed by `/api/v1/*` route handlers.

New generated artifacts include:

- `glossary.json`
- `learn_baseline_plane_<id>.json`
- recommendation files with full-month `calendarDays` + score breakdowns

## API Surface (Mock-Compatible)

- `GET /api/v1/planes`
- `GET /api/v1/planes/:planeId/health`
- `GET /api/v1/planes/:planeId/soh-trend?window=30d|90d|1y`
- `GET /api/v1/planes/:planeId/flights?limit=...`
- `GET /api/v1/planes/:planeId/predictions`
- `GET /api/v1/planes/:planeId/recommendations?month=YYYY-MM`
- `GET /api/v1/weather?airport=ICAO&start=YYYY-MM-DD&end=YYYY-MM-DD`
- `GET /api/v1/glossary`
- `GET /api/v1/learn/baseline?planeId=...`

All responses are validated with Zod schemas in `lib/contracts/schemas.ts`.

## Route Map

- `/` cinematic landing page
- `/experience` guided overview
- `/planes` fleet list
- `/planes/[planeId]` detailed plane dashboard
- `/learn` interactive SOH factor simulator

## Vercel Free Tier Deployment Runbook

1. Push repository to GitHub and ensure `frontend/` is committed.
2. In Vercel, click `Add New Project` and import the repo.
3. Set project root directory to `frontend`.
4. Framework preset: `Next.js`.
5. Build command: `npm run build`.
6. Install command: `npm install`.
7. Output directory: default (leave blank).
8. Production branch: `main`.
9. Enable Preview Deployments for pull requests.
10. Use the generated default `*.vercel.app` URL for presentation day.

## Testing Note

- `npm run test:e2e` is intentionally lightweight (skips full Playwright run) for rapid frontend iteration.
- Run `npm run test:e2e:full` when you want the complete end-to-end suite.
