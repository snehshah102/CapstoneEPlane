import { addDays } from "date-fns";

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

function formatUtcDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function parseUtcDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day, 12, 0, 0));
}

function daysBetweenUtc(a: string, b: string) {
  return Math.round((parseUtcDate(a).getTime() - parseUtcDate(b).getTime()) / 86_400_000);
}

function enumerateUtcDates(start: string, end: string) {
  const dates: Date[] = [];
  for (
    let cursor = parseUtcDate(start);
    cursor.getTime() <= parseUtcDate(end).getTime();
    cursor = new Date(cursor.getTime() + 86_400_000)
  ) {
    dates.push(cursor);
  }
  return dates;
}

function confidenceByOffset(offset: number): "high" | "medium" | "low" {
  if (offset <= 9) return "high";
  if (offset <= 21) return "medium";
  return "low";
}

export function summarizeWeatherDay(tempMaxC: number, precipMm: number, windKph: number) {
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
    date: formatUtcDate(date),
    tempMinC: Number(tempMin.toFixed(1)),
    tempMaxC: Number(tempMax.toFixed(1)),
    precipMm: Number(precip.toFixed(1)),
    windKph: Number(wind.toFixed(1)),
    summary: summarizeWeatherDay(tempMax, precip, wind),
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

export async function getWeatherPayload(airport: string, start: string, end: string) {
  const normalizedAirport = airport.toUpperCase();
  const airportMeta = AIRPORTS[normalizedAirport];
  if (!airportMeta) {
    throw new Error(`Unsupported airport code ${normalizedAirport}`);
  }

  const days = enumerateUtcDates(start, end);
  const forecastEnd = addDays(new Date(), 16);
  const endDate = parseUtcDate(end);
  const requestForecastEnd = endDate < forecastEnd ? endDate : forecastEnd;
  const forecastEndIso = formatUtcDate(requestForecastEnd);

  let observedDays: WeatherDay[] = [];
  try {
    const weather = await fetchOpenMeteo(airportMeta.lat, airportMeta.lon, start, forecastEndIso);
    const daily = weather?.daily;
    if (daily?.time?.length) {
      observedDays = daily.time.map((date: string, index: number) => {
        const offset = daysBetweenUtc(date, new Date().toISOString().slice(0, 10));
        const tempMax = Number(daily.temperature_2m_max[index] ?? 0);
        const tempMin = Number(daily.temperature_2m_min[index] ?? 0);
        const precip = Number(daily.precipitation_sum[index] ?? 0);
        const wind = Number(daily.wind_speed_10m_max[index] ?? 0);
        return {
          date,
          tempMinC: tempMin,
          tempMaxC: tempMax,
          precipMm: precip,
          windKph: wind,
          summary: summarizeWeatherDay(tempMax, precip, wind),
          confidenceTier: confidenceByOffset(offset)
        };
      });
    }
  } catch {
    observedDays = [];
  }

  const observedMap = new Map(observedDays.map((item) => [item.date, item]));
  const merged = days.map((date) => {
    const iso = formatUtcDate(date);
    const existing = observedMap.get(iso);
    if (existing) return existing;
    const offset = daysBetweenUtc(iso, new Date().toISOString().slice(0, 10));
    return modeledDay(date, offset);
  });

  return WeatherResponseSchema.parse({
    airport: normalizedAirport,
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
}
