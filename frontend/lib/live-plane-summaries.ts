import { promises as fs } from "fs";
import path from "path";

import { riskBandFromSoh, type RiskBand } from "@/lib/soh-health-bands";
import { readPlaneKpisSnapshot, readPlanesSnapshot } from "@/lib/snapshot-store";

type PlaneSummaryRecord = {
  planeId: string;
  registration: string;
  aircraftType: string;
  flightsCount: number;
  chargingEventsCount: number;
  sohCurrent: number;
  sohTrend30: number;
  riskBand: RiskBand;
  updatedAt: string;
};

type PlanePoint = {
  ts: number;
  soh: number;
};

const LIVE_CACHE_TTL_MS = 60_000;
let cachedAtMs = 0;
let cachedPayload: { planes: PlaneSummaryRecord[] } | null = null;

async function fileExists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function resolveRepoRoot(): Promise<string> {
  const cwd = process.cwd();
  const parent = path.resolve(cwd, "..");
  if (await fileExists(path.join(parent, "ml_workspace"))) {
    return parent;
  }
  if (await fileExists(path.join(cwd, "ml_workspace"))) {
    return cwd;
  }
  return parent;
}

function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (ch === "," && !inQuotes) {
      out.push(current);
      current = "";
      continue;
    }
    current += ch;
  }
  out.push(current);
  return out;
}

function parseLatentCsv(csvText: string): {
  flightsCount: number;
  chargingEventsCount: number;
  points: PlanePoint[];
} {
  const lines = csvText.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (lines.length < 2) {
    return { flightsCount: 0, chargingEventsCount: 0, points: [] };
  }

  const header = splitCsvLine(lines[0]);
  const idxType = header.indexOf("event_type");
  const idxDatetime = header.indexOf("event_datetime");
  const idxSoh = header.indexOf("latent_soh_filter_pct");
  if (idxType < 0 || idxDatetime < 0 || idxSoh < 0) {
    return { flightsCount: 0, chargingEventsCount: 0, points: [] };
  }

  let flightsCount = 0;
  let chargingEventsCount = 0;
  const points: PlanePoint[] = [];

  for (let i = 1; i < lines.length; i += 1) {
    const cols = splitCsvLine(lines[i]);
    if (cols.length <= Math.max(idxType, idxDatetime, idxSoh)) {
      continue;
    }
    const eventType = String(cols[idxType] ?? "").trim().toLowerCase();
    if (eventType === "flight") {
      flightsCount += 1;
    }
    if (eventType.includes("charge")) {
      chargingEventsCount += 1;
    }

    const ts = Date.parse(String(cols[idxDatetime] ?? ""));
    const soh = Number(cols[idxSoh]);
    if (Number.isFinite(ts) && Number.isFinite(soh)) {
      points.push({ ts, soh });
    }
  }

  points.sort((a, b) => a.ts - b.ts);
  return { flightsCount, chargingEventsCount, points };
}

async function computeLivePlaneSummary(
  repoRoot: string,
  planeId: string,
  registration: string,
  aircraftType: string
): Promise<PlaneSummaryRecord> {
  const latentPath = path.join(
    repoRoot,
    "ml_workspace",
    "latent_soh",
    "output",
    `plane_${planeId}`,
    "latent_soh_event_table.csv"
  );
  const nowIso = new Date().toISOString();

  if (!(await fileExists(latentPath))) {
    const fallback = await readPlaneKpisSnapshot(planeId);
    const health = fallback.health as {
      sohCurrent?: number;
      sohTrend30?: number;
      updatedAt?: string;
      riskBand?: "low" | "medium" | "watch" | "critical" | "decline" | "high";
    };
    const sohCurrent = Number(health.sohCurrent ?? 0);
    return {
      planeId,
      registration,
      aircraftType,
      flightsCount: 0,
      chargingEventsCount: 0,
      sohCurrent,
      sohTrend30: Number(health.sohTrend30 ?? 0),
      riskBand: riskBandFromSoh(sohCurrent),
      updatedAt: health.updatedAt ?? nowIso
    };
  }

  const rawCsv = await fs.readFile(latentPath, "utf8");
  const parsed = parseLatentCsv(rawCsv);
  if (parsed.points.length === 0) {
    return {
      planeId,
      registration,
      aircraftType,
      flightsCount: parsed.flightsCount,
      chargingEventsCount: parsed.chargingEventsCount,
      sohCurrent: 0,
      sohTrend30: 0,
      riskBand: "critical",
      updatedAt: nowIso
    };
  }

  const latest = parsed.points[parsed.points.length - 1];
  const cutoff = latest.ts - 30 * 24 * 60 * 60 * 1000;
  const window = parsed.points.filter((point) => point.ts >= cutoff);
  const sohTrend30 =
    window.length >= 2 ? window[window.length - 1].soh - window[0].soh : 0;
  const sohCurrent = latest.soh;

  return {
    planeId,
    registration,
    aircraftType,
    flightsCount: parsed.flightsCount,
    chargingEventsCount: parsed.chargingEventsCount,
    sohCurrent,
    sohTrend30,
    riskBand: riskBandFromSoh(sohCurrent),
    updatedAt: new Date(latest.ts).toISOString()
  };
}

export async function getLivePlanesPayload(): Promise<{ planes: PlaneSummaryRecord[] }> {
  const now = Date.now();
  if (cachedPayload && now - cachedAtMs < LIVE_CACHE_TTL_MS) {
    return cachedPayload;
  }

  const repoRoot = await resolveRepoRoot();
  const snapshot = await readPlanesSnapshot();
  const snapshotPlanes = (snapshot.planes ?? []) as Array<{
    planeId?: string;
    registration?: string;
    aircraftType?: string;
  }>;

  const livePlanes = await Promise.all(
    snapshotPlanes
      .filter((plane): plane is { planeId: string; registration?: string; aircraftType?: string } =>
        typeof plane.planeId === "string" && plane.planeId.length > 0
      )
      .map((plane) =>
        computeLivePlaneSummary(
          repoRoot,
          plane.planeId,
          plane.registration ?? `Plane ${plane.planeId}`,
          plane.aircraftType ?? "Unknown aircraft"
        )
      )
  );

  const payload = { planes: livePlanes };
  cachedPayload = payload;
  cachedAtMs = now;
  return payload;
}
