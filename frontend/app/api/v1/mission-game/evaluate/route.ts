import { NextResponse } from "next/server";

import { AIRPORTS } from "@/lib/airports";
import {
  MissionGameEvaluateResponseSchema,
  MissionGameInputSchema,
  MissionGamePlaneResult
} from "@/lib/contracts/schemas";
import {
  readPlaneKpisSnapshot,
  readPlaneRecommendationsSnapshot,
  readPlanesSnapshot
} from "@/lib/snapshot-store";

const PAYLOAD_FACTOR: Record<"light" | "medium" | "heavy", number> = {
  light: 0.9,
  medium: 1,
  heavy: 1.12
};

function clamp(value: number, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function statusFromScore(score: number) {
  if (score >= 78) return "recommended" as const;
  if (score >= 60) return "caution" as const;
  return "not_recommended" as const;
}

function fallbackRateUsdPerKwh(state: string, country: "US" | "CA" | "ZA") {
  const hash = state
    .split("")
    .reduce((acc, char) => acc + char.charCodeAt(0), 0);
  const base = country === "US" ? 0.17 : country === "CA" ? 0.15 : 0.13;
  return Number((base + ((hash % 7) - 3) * 0.005).toFixed(3));
}

function weatherScoreFromManual(tempC: number, windKph: number, precipMm: number) {
  const tempPenalty = Math.abs(tempC - 21) * 1.3;
  const windPenalty = Math.max(0, windKph - 12) * 1.2;
  const precipPenalty = precipMm * 3.5;
  return clamp(100 - tempPenalty - windPenalty - precipPenalty);
}

function recommendationForDate(
  recommendations: {
    calendarDays?: Array<{
      date: string;
      score: number;
      confidenceTier: "high" | "medium" | "low";
      weatherSummary: string;
    }>;
  },
  date: string
) {
  return (
    recommendations.calendarDays?.find((day) => day.date === date) ??
    recommendations.calendarDays?.[0] ??
    null
  );
}

function suggestionsFromInputs(input: {
  targetSoc: number;
  plannedDurationMin: number;
  routeDistanceKm: number;
  payloadLevel: "light" | "medium" | "heavy";
  weatherMode: "forecast" | "manual";
  manualWeather?: { windKph: number; precipMm: number };
}) {
  const suggestions: Array<{ action: string; expectedScoreDelta: number }> = [];
  if (input.targetSoc > 85) {
    suggestions.push({
      action: "Lower charge target to 80-85% when mission margin allows.",
      expectedScoreDelta: 6
    });
  }
  if (input.plannedDurationMin > 80 || input.routeDistanceKm > 160) {
    suggestions.push({
      action: "Split into shorter mission segments to reduce sustained stress.",
      expectedScoreDelta: 5
    });
  }
  if (input.payloadLevel === "heavy") {
    suggestions.push({
      action: "Reduce payload where possible to improve energy efficiency.",
      expectedScoreDelta: 4
    });
  }
  if (
    input.weatherMode === "manual" &&
    (input.manualWeather?.windKph ?? 0) > 22
  ) {
    suggestions.push({
      action: "Shift departure window to lower wind conditions.",
      expectedScoreDelta: 5
    });
  }
  if (
    input.weatherMode === "manual" &&
    (input.manualWeather?.precipMm ?? 0) > 2
  ) {
    suggestions.push({
      action: "Delay mission until precipitation weakens.",
      expectedScoreDelta: 4
    });
  }
  if (suggestions.length === 0) {
    suggestions.push({
      action: "Current mission plan is balanced; maintain this profile.",
      expectedScoreDelta: 2
    });
  }
  return suggestions.slice(0, 3);
}

async function evaluatePlane(
  planeId: string,
  input: {
    date: string;
    plannedDurationMin: number;
    routeDistanceKm: number;
    targetSoc: number;
    payloadLevel: "light" | "medium" | "heavy";
    weatherMode: "forecast" | "manual";
    manualWeather?: { tempC: number; windKph: number; precipMm: number };
  },
  registration: string
): Promise<MissionGamePlaneResult & { why: string[] }> {
  const kpis = await readPlaneKpisSnapshot(planeId);
  const month = input.date.slice(0, 7);
  const recs = await readPlaneRecommendationsSnapshot(planeId, month);

  const health = kpis.health as {
    sohCurrent: number;
    confidence: number;
    lastFlight?: { departureAirport?: string | null };
  };
  const rec = recommendationForDate(
    recs.recommendations as {
      calendarDays?: Array<{
        date: string;
        score: number;
        confidenceTier: "high" | "medium" | "low";
        weatherSummary: string;
      }>;
    },
    input.date
  );

  const baseBattery = clamp(
    0.55 * health.sohCurrent +
      0.3 * (rec?.score ?? 70) +
      0.15 * (100 - Math.max(0, input.targetSoc - 80) * 2.2)
  );
  const missionStress =
    (input.plannedDurationMin / 120) * 18 +
    (input.routeDistanceKm / 220) * 16 +
    (PAYLOAD_FACTOR[input.payloadLevel] - 1) * 40;
  const batteryImpact = clamp(baseBattery - missionStress);

  const forecastWeather = clamp((rec?.score ?? 72) - 8);
  const manualWeather =
    input.weatherMode === "manual" && input.manualWeather
      ? weatherScoreFromManual(
          input.manualWeather.tempC,
          input.manualWeather.windKph,
          input.manualWeather.precipMm
        )
      : forecastWeather;
  const confidenceWeight = (health.confidence ?? 0.8) * 100;
  const safetyConfidence = clamp(0.62 * manualWeather + 0.38 * confidenceWeight);

  const airportCode =
    health.lastFlight?.departureAirport?.slice(0, 4).toUpperCase() ?? "CYKF";
  const airport = AIRPORTS[airportCode] ?? AIRPORTS.CYKF;
  const costPerKwh = fallbackRateUsdPerKwh(airport.state, airport.country);
  const energyKwh =
    ((input.routeDistanceKm / 2.6) * PAYLOAD_FACTOR[input.payloadLevel] +
      input.plannedDurationMin * 0.16) *
    (input.targetSoc / 100);
  const estimatedCostUsd = Number((energyKwh * costPerKwh).toFixed(2));
  const costEfficiency = clamp(100 - estimatedCostUsd * 1.55);

  const overallScore = Number(
    clamp(0.45 * batteryImpact + 0.35 * safetyConfidence + 0.2 * costEfficiency).toFixed(
      2
    )
  );
  const estimatedBatteryImpact = Number(clamp(100 - batteryImpact).toFixed(2));
  const status = statusFromScore(overallScore);

  const why: string[] = [];
  if ((rec?.score ?? 0) >= 75) why.push("Selected day is favorable for lower battery strain.");
  else why.push("Selected day has moderate mission stress signals.");
  if (input.targetSoc > 85)
    why.push("Higher charge target increases high-voltage stress exposure.");
  else why.push("Charge target is within a battery-friendly operating window.");
  if (costEfficiency >= 70) why.push("Expected charging cost is operationally efficient.");
  else why.push("Expected charging cost is elevated for this mission profile.");

  return {
    planeId,
    registration,
    overallScore,
    status,
    breakdown: {
      batteryImpact: Number(batteryImpact.toFixed(2)),
      safetyConfidence: Number(safetyConfidence.toFixed(2)),
      costEfficiency: Number(costEfficiency.toFixed(2))
    },
    estimatedCostUsd,
    estimatedBatteryImpact,
    why: why.slice(0, 3)
  };
}

export async function POST(request: Request) {
  const body = await request.json();
  const input = MissionGameInputSchema.parse(body);
  const planes = await readPlanesSnapshot();
  const planeMap = new Map(
    (planes.planes as Array<{ planeId: string; registration: string }>).map((plane) => [
      plane.planeId,
      plane.registration
    ])
  );

  const selectedPlaneIds =
    input.mode === "single" ? [input.planeIds[0]] : Array.from(new Set(input.planeIds));

  const planeResultsRaw = await Promise.all(
    selectedPlaneIds.map((planeId) =>
      evaluatePlane(
        planeId,
        {
          date: input.date,
          plannedDurationMin: input.plannedDurationMin,
          routeDistanceKm: input.routeDistanceKm,
          targetSoc: input.targetSoc,
          payloadLevel: input.payloadLevel,
          weatherMode: input.weatherMode,
          manualWeather: input.manualWeather
        },
        planeMap.get(planeId) ?? `Plane ${planeId}`
      )
    )
  );
  const sorted = [...planeResultsRaw].sort((a, b) => b.overallScore - a.overallScore);
  const primary = sorted[0];
  const suggestions = suggestionsFromInputs({
    targetSoc: input.targetSoc,
    plannedDurationMin: input.plannedDurationMin,
    routeDistanceKm: input.routeDistanceKm,
    payloadLevel: input.payloadLevel,
    weatherMode: input.weatherMode,
    manualWeather: input.manualWeather
  });

  const payload = MissionGameEvaluateResponseSchema.parse({
    result: {
      overallScore: primary.overallScore,
      status: primary.status,
      breakdown: primary.breakdown,
      estimatedCostUsd: primary.estimatedCostUsd,
      estimatedBatteryImpact: primary.estimatedBatteryImpact,
      why: primary.why,
      suggestions,
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

  return NextResponse.json(payload);
}
