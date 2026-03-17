# AeroCell Frontend

Student-facing Next.js 15 application for battery SOH analytics, recommendation guidance,
charging-cost estimation, and explainable learning interactions.

## Commands

```powershell
npm install
npm run snapshots
npm run dev
npm run build
npm run lint
```

## Snapshot Pipeline

Builds typed JSON snapshots from parquet sources:

- `../data/event_manifest.parquet`
- `../data/event_timeseries.parquet`

Output files are created in `public/snapshots/` and consumed by `/api/v1/*` route handlers.

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
- `GET /api/v1/charging-cost?airport=ICAO&date=YYYY-MM-DD&energyKwh=number`
- `GET /api/v1/glossary`
- `GET /api/v1/learn/baseline?planeId=...`

All responses are validated with Zod schemas in `lib/contracts/schemas.ts`.

## Route Map

- `/` cinematic landing page
- `/planes` fleet list
- `/planes/[planeId]` detailed plane dashboard
- `/learn` interactive SOH factor simulator

## Production Deployment (Render)

This app is deployed most safely as a single Dockerized Render web service.
That matches local behavior closely because the production service includes:

- the Next.js app in `frontend/`
- the Python live-data scripts in `frontend/scripts/`
- the repo data and model outputs in `data/` and `ml_workspace/`

Deployment files now live at the repo root:

- `../Dockerfile`
- `../render.yaml`
- `../requirements.txt`

### One-time setup

1. Push the whole repository to GitHub, including:
   - `frontend/`
   - `data/`
   - `ml_workspace/`
   - `Dockerfile`
   - `render.yaml`
   - `requirements.txt`
2. Create a Render account and connect your GitHub account.
3. In Render, create a new service from this repo.
4. Use the repo-root `render.yaml` Blueprint or choose the repo and let Render build from `Dockerfile`.
5. If prompted for environment variables:
   - set `NODE_ENV=production`
   - set `PORT=10000`
   - set `PYTHON=python3`
   - optionally set `EIA_API_KEY` if you want live US charging-cost pricing
6. Let Render complete the first Docker build and deploy.

### Auto-deploy behavior

- The repo is configured for commit-based auto-deploys in `render.yaml`.
- After the first service is linked to GitHub, each push to the linked branch should trigger a fresh deploy automatically.

### Important free-tier note

- Render Free web services spin down after 15 minutes of no traffic and can take about a minute to wake up again.
- If you need always-on presentation readiness, use a paid instance type instead of Free.

## Testing Note

- Fast iteration policy for this phase: use `npm run lint` + `npm run build`.
- `npm run test:e2e` remains lightweight and intentionally skipped by default.
