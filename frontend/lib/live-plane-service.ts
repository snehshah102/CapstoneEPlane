import { runPythonJson } from "@/lib/live-python";
const LIVE_TTL_MS = 60_000;

type LivePlanePayload = {
  planeId: string;
  metadata: {
    registration: string;
    aircraftType: string;
  };
  health: Record<string, unknown>;
  prediction: Record<string, unknown>;
  trend: {
    planeId: string;
    points: unknown[];
  };
  history: {
    planeId: string;
    points: unknown[];
  };
  flights: {
    planeId: string;
    flights: unknown[];
  };
  ops?: {
    flightsPerDayRecent?: number;
  };
};

type CacheEntry = {
  expiresAt: number;
  value?: LivePlanePayload;
  promise?: Promise<LivePlanePayload>;
};

const planeCache = new Map<string, CacheEntry>();

async function runLivePlaneScript(planeId: string): Promise<LivePlanePayload> {
  const parsed = await runPythonJson<LivePlanePayload>("live_plane_data.py", [
    "--plane-id",
    planeId
  ]);
  if (!parsed || parsed.planeId !== planeId) {
    throw new Error(`Unexpected live payload for plane ${planeId}`);
  }
  return parsed;
}

export async function getLivePlanePayload(planeId: string): Promise<LivePlanePayload> {
  const now = Date.now();
  const cached = planeCache.get(planeId);
  if (cached?.value && cached.expiresAt > now) {
    return cached.value;
  }
  if (cached?.promise) {
    return cached.promise;
  }

  const promise = runLivePlaneScript(planeId)
    .then((value) => {
      planeCache.set(planeId, {
        value,
        expiresAt: Date.now() + LIVE_TTL_MS
      });
      return value;
    })
    .catch((error) => {
      planeCache.delete(planeId);
      throw error;
    });

  planeCache.set(planeId, {
    expiresAt: now + LIVE_TTL_MS,
    promise
  });

  return promise;
}
