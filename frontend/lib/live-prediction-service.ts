import { runPythonJson } from "@/lib/live-python";

const LIVE_TTL_MS = 60_000;

type LivePredictionPayload = {
  prediction: {
    planeId: string;
    forecast: {
      replacementDatePred: string;
      rulDaysPred: number;
      rulCyclesPred: number;
      confidence: number;
    };
    forecastCurve: Array<{
      date: string;
      soh: number;
    }>;
    sohTargetBlend: number;
    sohProxyPoh: number;
    sohObservedNorm: number;
  };
};

type CacheEntry = {
  expiresAt: number;
  value?: LivePredictionPayload;
  promise?: Promise<LivePredictionPayload>;
};

const predictionCache = new Map<string, CacheEntry>();

async function runLivePredictionScript(planeId: string): Promise<LivePredictionPayload> {
  return runPythonJson<LivePredictionPayload>("live_model_outputs.py", [
    "--plane-id",
    planeId
  ]);
}

export async function getLivePredictionPayload(
  planeId: string
): Promise<LivePredictionPayload> {
  const now = Date.now();
  const cached = predictionCache.get(planeId);
  if (cached?.value && cached.expiresAt > now) {
    return cached.value;
  }
  if (cached?.promise) {
    return cached.promise;
  }

  const promise = runLivePredictionScript(planeId)
    .then((value) => {
      predictionCache.set(planeId, {
        value,
        expiresAt: Date.now() + LIVE_TTL_MS
      });
      return value;
    })
    .catch((error) => {
      predictionCache.delete(planeId);
      throw error;
    });

  predictionCache.set(planeId, {
    expiresAt: now + LIVE_TTL_MS,
    promise
  });

  return promise;
}
