import { airportFromLabel } from "@/lib/airports";
import { getChargingCostEstimatePayload } from "@/lib/charging-cost-service";
import {
  MissionGameBaselineResponseSchema,
  MissionGameEvaluateResponseSchema,
  type MissionGameInput,
  type MissionGamePlaneResult
} from "@/lib/contracts/schemas";
import { getLivePlanePayload } from "@/lib/live-plane-service";
import { getLivePlanesPayload } from "@/lib/live-plane-summaries";
import { getLivePredictionPayload } from "@/lib/live-prediction-service";
import { getLiveRecommendationModelPayload } from "@/lib/live-recommendation-service";
import { getWeatherPayload } from "@/lib/weather-service";

const BASELINE_CACHE_TTL_MS = 5 * 60_000;

type MissionBaselinePayload = ReturnType<typeof MissionGameBaselineResponseSchema.parse>;
type BaselineCacheEntry = {
  expiresAt: number;
  value?: MissionBaselinePayload;
  promise?: Promise<MissionBaselinePayload>;
};

let baselineCacheEntry: BaselineCacheEntry | null = null;

const PAYLOAD_FACTOR: Record<"light" | "medium" | "heavy", number> = {
  light: 0.9,
  medium: 1,
  heavy: 1.12
};

function clamp(value: number, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function round(value: number, digits = 2) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function statusFromScore(score: number) {
  if (score >= 78) return "recommended" as const;
  if (score >= 60) return "caution" as const;
  return "not_recommended" as const;
}

function weatherScore(tempC: number, windKph: number, precipMm: number) {
  const tempPenalty =
    Math.abs(tempC - 21) * 1.25 +
    Math.max(0, 4 - tempC) * 1.1 +
    Math.max(0, tempC - 31) * 1.35;
  const windPenalty = Math.max(0, windKph - 12) * 1.35;
  const precipPenalty = precipMm * 4.4;
  return clamp(100 - tempPenalty - windPenalty - precipPenalty);
}

function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number) {
  const toRad = (value: number) => (value * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function routeDistanceFromAirports(
  departureAirport: string | null | undefined,
  destinationAirport: string | null | undefined
) {
  const departure = airportFromLabel(departureAirport);
  const destination = airportFromLabel(destinationAirport);
  if (!departure || !destination) {
    return 120;
  }
  return Math.max(10, Math.round(distanceKm(departure.lat, departure.lon, destination.lat, destination.lon)));
}

function suggestionsFromDrivers(drivers: Array<{ action: string; delta: number }>) {
  return drivers
    .filter((driver) => driver.delta > 0.5)
    .sort((a, b) => b.delta - a.delta)
    .slice(0, 3)
    .map((driver) => ({
      action: driver.action,
      expectedScoreDelta: round(driver.delta, 1)
    }));
}

async function evaluatePlane(
  planeId: string,
  input: MissionGameInput,
  scoringWeights: { battery: number; safety: number; cost: number }
): Promise<MissionGamePlaneResult & { why: string[]; suggestionDrivers: Array<{ action: string; delta: number }> }> {
  const [live, predictionPayload, recommendationPayload] = await Promise.all([
    getLivePlanePayload(planeId),
    getLivePredictionPayload(planeId),
    getLiveRecommendationModelPayload(planeId, input.date.slice(0, 7))
  ]);

  const health = live.health as {
    healthScore: number;
    sohCurrent: number;
    currentChargeSoc: number;
    lastFlight: {
      durationMin: number | null;
      departureAirport: string | null;
      destinationAirport: string | null;
    };
  };
  const metadata = live.metadata as {
    registration: string;
  };
  const departureAirport = airportFromLabel(health.lastFlight.departureAirport)?.icao ?? "CYKF";
  const forecastWeather =
    input.weatherMode === "manual"
      ? null
      : (await getWeatherPayload(departureAirport, input.date, input.date)).days[0] ?? null;
  const weatherInput = input.weatherMode === "manual"
    ? {
        tempC: input.manualWeather?.tempC ?? 21,
        windKph: input.manualWeather?.windKph ?? 12,
        precipMm: input.manualWeather?.precipMm ?? 0
      }
    : {
        tempC: forecastWeather ? (forecastWeather.tempMinC + forecastWeather.tempMaxC) / 2 : 21,
        windKph: forecastWeather?.windKph ?? 12,
        precipMm: forecastWeather?.precipMm ?? 0
      };

  const modelDay =
    recommendationPayload.modelDays.find((day) => day.date === input.date) ??
    recommendationPayload.modelDays[0];
  const weatherConfidence = weatherScore(
    weatherInput.tempC,
    weatherInput.windKph,
    weatherInput.precipMm
  );
  const recentDuration = health.lastFlight.durationMin ?? 55;
  const payloadFactor = PAYLOAD_FACTOR[input.payloadLevel];
  const availableRangeKm =
    2.45 *
    health.sohCurrent *
    (input.targetSoc / 100) *
    (1 - Math.max(0, weatherInput.windKph - 10) / 220) *
    (1 / payloadFactor);
  const durationPenalty = Math.max(0, input.plannedDurationMin - recentDuration) * 0.16;
  const routePenalty = Math.max(0, input.routeDistanceKm - availableRangeKm * 0.82) * 0.12;
  const payloadPenalty = input.payloadLevel === "heavy" ? 8 : input.payloadLevel === "medium" ? 3 : 0;
  const chargePenalty = Math.max(0, input.targetSoc - 85) * 1.1;
  const reserveMarginScore = clamp((modelDay?.reserveMarginPct ?? 18) * 4.2, 0, 100);
  const batteryImpact = round(
    clamp(
      health.healthScore * 0.5 +
        (modelDay?.modelStressScore ?? 70) * 0.3 +
        (100 - chargePenalty * 2) * 0.2 -
        durationPenalty -
        routePenalty -
        payloadPenalty
    )
  );
  const safetyConfidence = round(
    clamp(
      predictionPayload.prediction.forecast.confidence * 100 * 0.4 +
        weatherConfidence * 0.35 +
        reserveMarginScore * 0.25
    )
  );
  const missionEnergyKwh = Math.max(
    18,
    input.routeDistanceKm / Math.max(availableRangeKm / 52, 1.2) +
      input.plannedDurationMin * 0.08 * payloadFactor
  );
  const chargeEnergyKwh = Math.max(
    missionEnergyKwh,
    missionEnergyKwh * 0.85 + Math.max(0, input.targetSoc - health.currentChargeSoc) * 0.38
  );
  const chargingEstimate = await getChargingCostEstimatePayload(
    departureAirport,
    input.date,
    round(chargeEnergyKwh, 1)
  );
  const costEfficiency = round(
    clamp(
      100 -
        chargingEstimate.estimate.estimatedSessionCostUsd * 1.7 -
        Math.max(0, chargeEnergyKwh - 55) * 0.45
    )
  );

  const overallScore = round(
    clamp(
      batteryImpact * scoringWeights.battery +
        safetyConfidence * scoringWeights.safety +
        costEfficiency * scoringWeights.cost
    )
  );
  const why = [
    `${metadata.registration} starts from live health score ${health.healthScore.toFixed(1)} with ${health.sohCurrent.toFixed(1)}% SOH.`,
    modelDay
      ? `Model projects ${modelDay.expectedDeltaSoh.toFixed(3)} SOH delta and ${modelDay.reserveMarginPct.toFixed(1)}% reserve margin for ${input.date}.`
      : "Mission timing is being evaluated without a model day match, so range margin is weighted more heavily.",
    `Charging estimate uses ${chargingEstimate.estimate.sourceMode} electricity pricing at ${departureAirport}.`
  ];
  const suggestionDrivers = [
    {
      action: "Lower target SOC toward 80-85% to reduce high-voltage dwell.",
      delta: Math.max(0, input.targetSoc - 85) * 0.45
    },
    {
      action: "Shorten the planned mission or split it into smaller legs.",
      delta: Math.max(0, input.plannedDurationMin - recentDuration) * 0.09
    },
    {
      action: "Reduce payload to improve reserve margin and energy efficiency.",
      delta: input.payloadLevel === "heavy" ? 5.5 : input.payloadLevel === "medium" ? 1.6 : 0
    },
    {
      action: "Shift to a calmer weather window when wind and precipitation ease.",
      delta: Math.max(0, 75 - weatherConfidence) * 0.08
    },
    {
      action: "Choose a shorter route or add a recharge stop to protect range margin.",
      delta: Math.max(0, input.routeDistanceKm - availableRangeKm * 0.82) * 0.07
    }
  ];

  return {
    planeId,
    registration: metadata.registration,
    overallScore,
    status: statusFromScore(overallScore),
    breakdown: {
      batteryImpact,
      safetyConfidence,
      costEfficiency
    },
    estimatedCostUsd: chargingEstimate.estimate.estimatedSessionCostUsd,
    estimatedBatteryImpact: round(clamp(100 - batteryImpact)),
    why,
    suggestionDrivers
  };
}

async function computeMissionGameBaselinePayload(): Promise<MissionBaselinePayload> {
  const planes = await getLivePlanesPayload();
  const defaultPlane = planes.planes[0]?.planeId ?? "166";
  const live = await getLivePlanePayload(defaultPlane);
  const health = live.health as {
    currentChargeSoc: number;
    lastFlight: {
      departureAirport: string | null;
      destinationAirport: string | null;
      durationMin: number | null;
    };
  };
  const departureAirport = airportFromLabel(health.lastFlight.departureAirport)?.icao ?? "CYKF";
  const today = new Date().toISOString().slice(0, 10);
  const weather = await getWeatherPayload(departureAirport, today, today);
  const weatherDay = weather.days[0];
  const routeDistanceKm = routeDistanceFromAirports(
    health.lastFlight.departureAirport,
    health.lastFlight.destinationAirport
  );

  return MissionGameBaselineResponseSchema.parse({
    baseline: {
      defaults: {
        date: today,
        plannedDurationMin: Math.max(20, Math.min(180, health.lastFlight.durationMin ?? 55)),
        routeDistanceKm,
        targetSoc: round(clamp(Math.max(80, health.currentChargeSoc + 8), 50, 95), 0),
        payloadLevel: "medium",
        weatherMode: "forecast",
        manualWeather: {
          tempC: round(weatherDay ? (weatherDay.tempMinC + weatherDay.tempMaxC) / 2 : 21, 1),
          windKph: round(weatherDay?.windKph ?? 12, 1),
          precipMm: round(weatherDay?.precipMm ?? 0, 1)
        }
      },
      scoringWeights: {
        battery: 0.45,
        safety: 0.35,
        cost: 0.2,
        version: "mission_live_v2"
      }
    }
  });
}

export async function getMissionGameBaselinePayload(): Promise<MissionBaselinePayload> {
  const now = Date.now();
  if (baselineCacheEntry?.value && baselineCacheEntry.expiresAt > now) {
    return baselineCacheEntry.value;
  }
  if (baselineCacheEntry?.promise) {
    return baselineCacheEntry.promise;
  }

  const promise = computeMissionGameBaselinePayload()
    .then((value) => {
      baselineCacheEntry = {
        value,
        expiresAt: Date.now() + BASELINE_CACHE_TTL_MS
      };
      return value;
    })
    .catch((error) => {
      baselineCacheEntry = null;
      throw error;
    });

  baselineCacheEntry = {
    expiresAt: now + BASELINE_CACHE_TTL_MS,
    promise
  };

  return promise;
}

export async function evaluateMissionGameLive(input: MissionGameInput) {
  const selectedPlaneIds =
    input.mode === "single" ? [input.planeIds[0]] : Array.from(new Set(input.planeIds));
  const scoringWeights = {
    battery: 0.45,
    safety: 0.35,
    cost: 0.2
  };

  const planeResultsRaw = await Promise.all(
    selectedPlaneIds.map((planeId) => evaluatePlane(planeId, input, scoringWeights))
  );
  const sorted = [...planeResultsRaw].sort((a, b) => b.overallScore - a.overallScore);
  const primary = sorted[0];
  const suggestions = suggestionsFromDrivers(primary.suggestionDrivers);

  return MissionGameEvaluateResponseSchema.parse({
    result: {
      overallScore: primary.overallScore,
      status: primary.status,
      breakdown: primary.breakdown,
      estimatedCostUsd: primary.estimatedCostUsd,
      estimatedBatteryImpact: primary.estimatedBatteryImpact,
      why: primary.why,
      suggestions: suggestions.length
        ? suggestions
        : [{ action: "Current mission profile is already balanced for the selected plane.", expectedScoreDelta: 1 }],
      evaluatedAt: new Date().toISOString(),
      perPlaneResults:
        input.mode === "fleet_compare"
          ? sorted.map((item) => ({
              planeId: item.planeId,
              registration: item.registration,
              overallScore: item.overallScore,
              status: item.status,
              breakdown: item.breakdown,
              estimatedCostUsd: item.estimatedCostUsd,
              estimatedBatteryImpact: item.estimatedBatteryImpact
            }))
          : undefined
    }
  });
}
