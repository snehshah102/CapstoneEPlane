import { runPythonJson } from "@/lib/live-python";
const LIVE_CACHE_TTL_MS = 60_000;

type PlaneSummaryRecord = {
  planeId: string;
  registration: string;
  aircraftType: string;
  flightsCount: number;
  chargingEventsCount: number;
  sohCurrent: number;
  sohTrend30: number;
  riskBand: "low" | "medium" | "watch" | "critical" | "decline" | "high";
  updatedAt: string;
};

type CacheEntry = {
  expiresAt: number;
  value?: { planes: PlaneSummaryRecord[] };
  promise?: Promise<{ planes: PlaneSummaryRecord[] }>;
};

let cacheEntry: CacheEntry | null = null;

async function runLivePlaneSummariesScript(): Promise<{ planes: PlaneSummaryRecord[] }> {
  const parsed = await runPythonJson<{ planes?: PlaneSummaryRecord[] }>(
    "live_plane_data.py",
    ["--list-planes"]
  );
  return {
    planes: Array.isArray(parsed.planes) ? parsed.planes : []
  };
}

export async function getLivePlanesPayload(): Promise<{ planes: PlaneSummaryRecord[] }> {
  const now = Date.now();
  if (cacheEntry?.value && cacheEntry.expiresAt > now) {
    return cacheEntry.value;
  }
  if (cacheEntry?.promise) {
    return cacheEntry.promise;
  }

  const promise = runLivePlaneSummariesScript()
    .then((value) => {
      cacheEntry = {
        value,
        expiresAt: Date.now() + LIVE_CACHE_TTL_MS
      };
      return value;
    })
    .catch((error) => {
      cacheEntry = null;
      throw error;
    });

  cacheEntry = {
    expiresAt: now + LIVE_CACHE_TTL_MS,
    promise
  };

  return promise;
}
