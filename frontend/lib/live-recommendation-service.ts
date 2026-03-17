import { runPythonJson } from "@/lib/live-python";

const LIVE_TTL_MS = 60_000;

export type LiveRecommendationModelDay = {
  date: string;
  modelStressScore: number;
  chargingScore: number;
  expectedDeltaSoh: number;
  postFlightSocPct: number;
  reserveMarginPct: number;
  targetSoc: number;
  chargeWindowStart: string;
  chargeWindowEnd: string;
  summary: string;
};

type LiveRecommendationModelPayload = {
  planeId: string;
  month: string;
  generatedAt: string;
  modelDays: LiveRecommendationModelDay[];
};

type CacheEntry = {
  expiresAt: number;
  value?: LiveRecommendationModelPayload;
  promise?: Promise<LiveRecommendationModelPayload>;
};

const recommendationCache = new Map<string, CacheEntry>();

async function runLiveRecommendationScript(
  planeId: string,
  month: string
): Promise<LiveRecommendationModelPayload> {
  return runPythonJson<LiveRecommendationModelPayload>("live_model_outputs.py", [
    "--plane-id",
    planeId,
    "--month",
    month
  ]);
}

export async function getLiveRecommendationModelPayload(
  planeId: string,
  month: string
): Promise<LiveRecommendationModelPayload> {
  const key = `${planeId}:${month}`;
  const now = Date.now();
  const cached = recommendationCache.get(key);
  if (cached?.value && cached.expiresAt > now) {
    return cached.value;
  }
  if (cached?.promise) {
    return cached.promise;
  }

  const promise = runLiveRecommendationScript(planeId, month)
    .then((value) => {
      recommendationCache.set(key, {
        value,
        expiresAt: Date.now() + LIVE_TTL_MS
      });
      return value;
    })
    .catch((error) => {
      recommendationCache.delete(key);
      throw error;
    });

  recommendationCache.set(key, {
    expiresAt: now + LIVE_TTL_MS,
    promise
  });

  return promise;
}
