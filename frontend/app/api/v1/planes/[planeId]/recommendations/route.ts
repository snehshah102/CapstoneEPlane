import { NextResponse } from "next/server";

import { AIRPORTS } from "@/lib/airports";
import { RecommendationsResponseSchema } from "@/lib/contracts/schemas";
import { getLivePlanePayload } from "@/lib/live-plane-service";
import {
  getLiveRecommendationModelPayload,
  type LiveRecommendationModelDay
} from "@/lib/live-recommendation-service";
import { getWeatherPayload } from "@/lib/weather-service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const revalidate = 0;

function clamp(value: number, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function normalizeMonth(value: string | null) {
  const candidate = value ?? new Date().toISOString().slice(0, 7);
  return /^\d{4}-\d{2}$/.test(candidate) ? candidate : new Date().toISOString().slice(0, 7);
}

function monthRange(month: string) {
  const [year, monthIndex] = month.split("-").map(Number);
  const start = `${year}-${String(monthIndex).padStart(2, "0")}-01`;
  const end = new Date(Date.UTC(year, monthIndex, 0)).toISOString().slice(0, 10);
  return {
    start,
    end
  };
}

function airportCodeFromLabel(label: string | null | undefined) {
  const code = label?.slice(0, 4).toUpperCase() ?? "CYKF";
  return AIRPORTS[code] ? code : "CYKF";
}

function confidenceFromOffset(offset: number): "high" | "medium" | "low" {
  if (offset <= 9) return "high";
  if (offset <= 21) return "medium";
  return "low";
}

function scoreSummary(
  dateIso: string,
  weatherPenalty: number,
  thermalPenalty: number,
  modelDay: LiveRecommendationModelDay | undefined,
  offset: number
) {
  if (offset < 0) return "Date has passed";
  if (modelDay && modelDay.reserveMarginPct < 0) {
    return "Reserve SOC margin is too tight for this mission.";
  }
  if (weatherPenalty > 24) return "Weather-driven wear risk is elevated";
  if (thermalPenalty > 18) return "Thermal stress is likely";
  if (modelDay && modelDay.expectedDeltaSoh <= -0.18) {
    return "Model projects a heavier degradation hit for this window.";
  }
  if (modelDay?.summary) return modelDay.summary;
  return `Favorable flight window on ${dateIso}`;
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ planeId: string }> }
) {
  const { planeId } = await params;
  const { searchParams } = new URL(request.url);
  const month = normalizeMonth(searchParams.get("month"));
  const { start, end } = monthRange(month);

  const live = await getLivePlanePayload(planeId);
  const airport = airportCodeFromLabel(
    (live.health as { lastFlight?: { departureAirport?: string | null } }).lastFlight?.departureAirport
  );
  const weather = await getWeatherPayload(airport, start, end);
  const modelRecommendations = await getLiveRecommendationModelPayload(planeId, month);
  const modelByDate = new Map(
    modelRecommendations.modelDays.map((day) => [day.date, day])
  );

  const health = live.health as {
    sohCurrent: number;
    sohTrend30: number;
    currentChargeSoc: number;
  };
  const todayIso = new Date().toISOString().slice(0, 10);

  const calendarDays = weather.days.map((day) => {
    const modelDay = modelByDate.get(day.date);
    const offset = Math.round(
      (Date.parse(`${day.date}T00:00:00Z`) - Date.parse(`${todayIso}T00:00:00Z`)) / 86_400_000
    );
    const weatherPenalty = day.precipMm * 3.1 + Math.max(0, day.windKph - 18) * 1.4;
    const tempMid = (day.tempMinC + day.tempMaxC) / 2;
    const thermalPenalty =
      Math.abs(tempMid - 21) * 1.35 +
      Math.max(0, 4 - day.tempMinC) * 0.9 +
      Math.max(0, day.tempMaxC - 31) * 1.1;

    const breakdown = {
      weather: Number(clamp(100 - weatherPenalty * 2.2).toFixed(2)),
      thermal: Number(clamp(100 - thermalPenalty * 2.6).toFixed(2)),
      stress: Number((modelDay?.modelStressScore ?? clamp(84 - Math.max(0, 82 - health.sohCurrent) * 1.1)).toFixed(2)),
      charging: Number((modelDay?.chargingScore ?? 72).toFixed(2))
    };
    const score = Number(
      clamp(
        breakdown.weather * 0.32 +
          breakdown.thermal * 0.24 +
          breakdown.stress * 0.28 +
          breakdown.charging * 0.16 -
          (offset < 0 ? 25 : 0) -
          (modelDay && modelDay.reserveMarginPct < 0 ? 18 : 0)
      ).toFixed(2)
    );

    return {
      date: day.date,
      score,
      confidenceTier: offset < 0 ? "low" : confidenceFromOffset(offset),
      weatherSummary: scoreSummary(day.date, weatherPenalty, thermalPenalty, modelDay, offset),
      breakdown
    };
  });

  const ranked = [...calendarDays]
    .filter((day) => day.date >= todayIso)
    .sort((a, b) => b.score - a.score || a.date.localeCompare(b.date));
  const topDays = (ranked.length > 0 ? ranked : [...calendarDays].sort((a, b) => b.score - a.score)).slice(
    0,
    10
  );

  const chargePlan = topDays.slice(0, 5).map((day) => {
    const modelDay = modelByDate.get(day.date);
    return {
      date: day.date,
      targetSoc: Number((modelDay?.targetSoc ?? 82).toFixed(0)),
      chargeWindowStart: modelDay?.chargeWindowStart ?? `${day.date}T05:30:00Z`,
      chargeWindowEnd: modelDay?.chargeWindowEnd ?? `${day.date}T08:00:00Z`,
      rationale:
        modelDay?.reserveMarginPct !== undefined && modelDay.reserveMarginPct < 0
          ? "Charge earlier or reduce mission demand to protect reserve SOC margin."
          : "Charge close to departure to reduce high-SOC dwell while preserving operational buffer."
    };
  });

  const bestDay = topDays[0];
  const weatherLimitedDays = calendarDays.filter((day) => day.breakdown.weather < 60).length;
  const reserveLimitedDays = modelRecommendations.modelDays.filter(
    (day) => day.reserveMarginPct < 0
  ).length;
  const modeledHighWearDays = modelRecommendations.modelDays.filter(
    (day) => day.expectedDeltaSoh <= -0.18
  ).length;
  const bestModelDay = bestDay ? modelByDate.get(bestDay.date) : undefined;
  const cards = [
    {
      id: "timing-best-day-live",
      type: "timing" as const,
      action: bestDay
        ? `Prioritize ${bestDay.date}; it is the strongest operating window this month.`
        : "Prioritize the highest-scoring days in this month.",
      confidence: bestDay?.confidenceTier === "high" ? 0.9 : bestDay?.confidenceTier === "medium" ? 0.8 : 0.7,
      why: [
        bestDay ? `Composite score is ${bestDay.score.toFixed(1)} for that day.` : "Scores blend live weather and model-backed mission stress.",
        bestModelDay
          ? `Model projects ${bestModelDay.expectedDeltaSoh.toFixed(3)} SOH delta for that mission day.`
          : "Mission stress is evaluated from the backend degradation model.",
        "Thermal and weather conditions are layered on top of the model-backed mission score."
      ]
    },
    {
      id: "charge-window-live",
      type: "charging" as const,
      action: `Target ${chargePlan[0]?.targetSoc ?? 82}% SOC and charge inside the model-selected window instead of holding a full pack early.`,
      confidence: 0.87,
      why: [
        "Charge timing is generated from the backend mission simulation state.",
        reserveLimitedDays > 0
          ? `${reserveLimitedDays} days this month would miss reserve margin without tighter charging discipline.`
          : "Current reserve margin stays healthy across the modeled month.",
        `Current battery trend is ${health.sohTrend30.toFixed(2)} SOH points over 30 days.`
      ]
    },
    {
      id: "avoid-weather-stress-live",
      type: weatherLimitedDays >= 6 || reserveLimitedDays > 0 ? ("dont" as const) : ("do" as const),
      action:
        weatherLimitedDays >= 6 || reserveLimitedDays > 0
          ? "Avoid days where weather or reserve margin pushes the mission into a tighter operating envelope."
          : "Use the calendar to spread flights across the steadier low-risk windows.",
      confidence: 0.8,
      why: [
        `${weatherLimitedDays} days this month show meaningfully worse weather scores.`,
        `${modeledHighWearDays} days show meaningfully worse model-projected degradation.`,
        `Current charge snapshot is ${health.currentChargeSoc.toFixed(1)}% SOC.`
      ]
    }
  ];

  const payload = RecommendationsResponseSchema.parse({
    recommendations: {
      planeId,
      month,
      generatedAt: modelRecommendations.generatedAt,
      flightDayScores: topDays.map((day) => ({
        date: day.date,
        score: day.score,
        confidenceTier: day.confidenceTier,
        weatherSummary: day.weatherSummary
      })),
      calendarDays: calendarDays.map((day) => ({
        date: day.date,
        score: day.score,
        confidenceTier: day.confidenceTier,
        weatherSummary: day.weatherSummary
      })),
      scoreBreakdownByDate: Object.fromEntries(
        calendarDays.map((day) => [day.date, day.breakdown])
      ),
      learnAssumptionsRef: "live_ops_calendar_v1",
      chargePlan,
      cards
    }
  });

  return NextResponse.json(payload);
}
