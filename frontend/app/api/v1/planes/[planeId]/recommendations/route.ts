import { NextResponse } from "next/server";

import { AIRPORTS } from "@/lib/airports";
import { RecommendationsResponseSchema } from "@/lib/contracts/schemas";
import { getLivePlanePayload } from "@/lib/live-plane-service";
import { getWeatherPayload } from "@/lib/weather-service";

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
  stressPenalty: number,
  offset: number
) {
  if (offset < 0) return "Date has passed";
  if (weatherPenalty > 24) return "Weather-driven wear risk is elevated";
  if (thermalPenalty > 18) return "Thermal stress is likely";
  if (stressPenalty > 18) return "Battery stress is elevated for this window";
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

  const health = live.health as {
    sohCurrent: number;
    sohTrend30: number;
    currentChargeSoc: number;
  };
  const flightsPerDayRecent = Number(live.ops?.flightsPerDayRecent ?? 0.2);
  const todayIso = new Date().toISOString().slice(0, 10);

  const calendarDays = weather.days.map((day) => {
    const offset = Math.round(
      (Date.parse(`${day.date}T00:00:00Z`) - Date.parse(`${todayIso}T00:00:00Z`)) / 86_400_000
    );
    const weatherPenalty = day.precipMm * 3.1 + Math.max(0, day.windKph - 18) * 1.4;
    const tempMid = (day.tempMinC + day.tempMaxC) / 2;
    const thermalPenalty =
      Math.abs(tempMid - 21) * 1.35 +
      Math.max(0, 4 - day.tempMinC) * 0.9 +
      Math.max(0, day.tempMaxC - 31) * 1.1;
    const stressPenalty =
      Math.max(0, 82 - health.sohCurrent) * 0.42 +
      Math.max(0, -health.sohTrend30) * 5.2 +
      flightsPerDayRecent * 7.5;
    const chargingPenalty =
      offset < 0 ? 65 : offset === 0 ? 30 : offset === 1 ? 14 : offset > 21 ? 18 : 6;

    const breakdown = {
      weather: Number(clamp(100 - weatherPenalty * 2.2).toFixed(2)),
      thermal: Number(clamp(100 - thermalPenalty * 2.6).toFixed(2)),
      stress: Number(clamp(100 - stressPenalty * 2.3).toFixed(2)),
      charging: Number(clamp(100 - chargingPenalty).toFixed(2))
    };
    const score = Number(
      clamp(
        breakdown.weather * 0.34 +
          breakdown.thermal * 0.28 +
          breakdown.stress * 0.24 +
          breakdown.charging * 0.14 -
          (offset < 0 ? 25 : 0)
      ).toFixed(2)
    );

    return {
      date: day.date,
      score,
      confidenceTier: offset < 0 ? "low" : confidenceFromOffset(offset),
      weatherSummary: scoreSummary(day.date, weatherPenalty, thermalPenalty, stressPenalty, offset),
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

  const targetSoc = health.sohCurrent >= 80 ? 82 : health.sohCurrent >= 60 ? 80 : 76;
  const chargePlan = topDays.slice(0, 5).map((day) => {
    const chargeOnDay = day.date <= todayIso ? day.date : new Date(`${day.date}T00:00:00Z`);
    const chargeDate =
      typeof chargeOnDay === "string"
        ? chargeOnDay
        : new Date(chargeOnDay.getTime() - 86_400_000).toISOString().slice(0, 10);
    const sameDay = chargeDate === day.date;
    return {
      date: day.date,
      targetSoc,
      chargeWindowStart: `${chargeDate}T${sameDay ? "05:30:00" : "18:30:00"}Z`,
      chargeWindowEnd: `${chargeDate}T${sameDay ? "08:00:00" : "21:15:00"}Z`,
      rationale:
        "Charge close to departure to reduce high-SOC dwell while preserving operational buffer."
    };
  });

  const bestDay = topDays[0];
  const weatherLimitedDays = calendarDays.filter((day) => day.breakdown.weather < 60).length;
  const cards = [
    {
      id: "timing-best-day-live",
      type: "timing" as const,
      action: bestDay
        ? `Prioritize ${bestDay.date}; it is the strongest operating window this month.`
        : "Prioritize the highest-scoring days in this month.",
      confidence: bestDay?.confidenceTier === "high" ? 0.9 : bestDay?.confidenceTier === "medium" ? 0.8 : 0.7,
      why: [
        bestDay ? `Composite score is ${bestDay.score.toFixed(1)} for that day.` : "Scores blend live weather and battery condition.",
        "Thermal and weather conditions are factored into the ranking.",
        "Battery stress is adjusted using current SOH and recent degradation trend."
      ]
    },
    {
      id: "charge-window-live",
      type: "charging" as const,
      action: `Target ${targetSoc}% SOC and charge close to departure instead of holding a full pack early.`,
      confidence: 0.87,
      why: [
        "Limiting time at very high SOC reduces avoidable calendar wear.",
        "The charge window adapts to the selected month and best days.",
        `Current battery trend is ${health.sohTrend30.toFixed(2)} SOH points over 30 days.`
      ]
    },
    {
      id: "avoid-weather-stress-live",
      type: weatherLimitedDays >= 6 ? ("dont" as const) : ("do" as const),
      action:
        weatherLimitedDays >= 6
          ? "Avoid days with stronger wind or precipitation spikes unless the mission is time-critical."
          : "Use the calendar to spread flights across the steadier low-risk weather windows.",
      confidence: 0.8,
      why: [
        `${weatherLimitedDays} days this month show meaningfully worse weather scores.`,
        `Recent flight cadence is about ${flightsPerDayRecent.toFixed(2)} flights/day.`,
        `Current charge snapshot is ${health.currentChargeSoc.toFixed(1)}% SOC.`
      ]
    }
  ];

  const payload = RecommendationsResponseSchema.parse({
    recommendations: {
      planeId,
      month,
      generatedAt: new Date().toISOString(),
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
