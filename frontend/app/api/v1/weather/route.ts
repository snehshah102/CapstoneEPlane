import { addDays, differenceInCalendarDays, eachDayOfInterval, formatISO } from "date-fns";
import { NextResponse } from "next/server";

import { AIRPORTS } from "@/lib/airports";
import { WeatherResponseSchema } from "@/lib/contracts/schemas";

type WeatherDay = {
  date: string;
  tempMinC: number;
  tempMaxC: number;
  precipMm: number;
  windKph: number;
  summary: string;
  confidenceTier: "high" | "medium" | "low";
};

function confidenceByOffset(offset: number): "high" | "medium" | "low" {
  if (offset <= 9) return "high";
  if (offset <= 21) return "medium";
  return "low";
}

function summarizeDay(tempMaxC: number, precipMm: number, windKph: number) {
  if (precipMm > 4.5 || windKph > 28) return "High wear-risk weather";
  if (tempMaxC < 3 || tempMaxC > 33) return "Thermally stressful window";
  return "Favorable flight window";
}

function modeledDay(date: Date, offset: number): WeatherDay {
  const month = date.getUTCMonth() + 1;
  const seasonalBaseline = 14 + 12 * Math.sin(((month - 3) / 12) * Math.PI * 2);
  const tempMax = seasonalBaseline + (offset % 5) - 2;
  const tempMin = tempMax - (6 + (offset % 3));
  const precip = Math.max(0, ((offset * 13) % 10) - 5) * 0.8;
  const wind = 12 + ((offset * 7) % 14);
  return {
    date: formatISO(date, { representation: "date" }),
    tempMinC: Number(tempMin.toFixed(1)),
    tempMaxC: Number(tempMax.toFixed(1)),
    precipMm: Number(precip.toFixed(1)),
    windKph: Number(wind.toFixed(1)),
    summary: summarizeDay(tempMax, precip, wind),
    confidenceTier: confidenceByOffset(offset)
  };
}

async function fetchOpenMeteo(lat: number, lon: number, start: string, end: string) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3_000);
  const url =
    `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}` +
    `&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max` +
    `&timezone=UTC&start_date=${start}&end_date=${end}`;

  try {
    const response = await fetch(url, {
      cache: "no-store",
      signal: controller.signal
    });
    if (!response.ok) {
      throw new Error("Weather service unavailable");
    }
    return response.json();
  } finally {
    clearTimeout(timeout);
  }
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const airport = (searchParams.get("airport") ?? "CYKF").toUpperCase();
  const start = searchParams.get("start") ?? formatISO(new Date(), { representation: "date" });
  const end = searchParams.get("end") ?? formatISO(addDays(new Date(), 30), { representation: "date" });

  const airportMeta = AIRPORTS[airport];
  if (!airportMeta) {
    return NextResponse.json({ error: `Unsupported airport code ${airport}` }, { status: 400 });
  }

  const startDate = new Date(`${start}T00:00:00Z`);
  const endDate = new Date(`${end}T00:00:00Z`);
  const days = eachDayOfInterval({ start: startDate, end: endDate });

  const forecastEnd = addDays(new Date(), 16);
  const requestForecastEnd = endDate < forecastEnd ? endDate : forecastEnd;
  const forecastEndIso = formatISO(requestForecastEnd, { representation: "date" });

  let observedDays: WeatherDay[] = [];
  try {
    const weather = await fetchOpenMeteo(airportMeta.lat, airportMeta.lon, start, forecastEndIso);
    const d = weather?.daily;
    if (d?.time?.length) {
      observedDays = d.time.map((date: string, index: number) => {
        const offset = differenceInCalendarDays(new Date(`${date}T00:00:00Z`), new Date());
        const tempMax = Number(d.temperature_2m_max[index] ?? 0);
        const tempMin = Number(d.temperature_2m_min[index] ?? 0);
        const precip = Number(d.precipitation_sum[index] ?? 0);
        const wind = Number(d.wind_speed_10m_max[index] ?? 0);
        return {
          date,
          tempMinC: tempMin,
          tempMaxC: tempMax,
          precipMm: precip,
          windKph: wind,
          summary: summarizeDay(tempMax, precip, wind),
          confidenceTier: confidenceByOffset(offset)
        };
      });
    }
  } catch {
    observedDays = [];
  }

  const observedMap = new Map(observedDays.map((item) => [item.date, item]));
  const merged = days.map((date) => {
    const iso = formatISO(date, { representation: "date" });
    const existing = observedMap.get(iso);
    if (existing) return existing;
    const offset = differenceInCalendarDays(date, new Date());
    return modeledDay(date, offset);
  });

  const payload = WeatherResponseSchema.parse({
    airport,
    start,
    end,
    mode:
      observedDays.length === 0
        ? "fallback"
        : observedDays.length >= days.length
          ? "live"
          : "mixed",
    demoMode: observedDays.length < days.length,
    days: merged
  });

  return NextResponse.json(payload);
}
