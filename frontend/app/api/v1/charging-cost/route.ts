import { NextResponse } from "next/server";

import { AIRPORTS } from "@/lib/airports";
import { ChargingCostResponseSchema } from "@/lib/contracts/schemas";

function fallbackRateUsdPerKwh(state: string, country: "US" | "CA" | "ZA") {
  const hash = state
    .split("")
    .reduce((acc, char) => acc + char.charCodeAt(0), 0);
  const base =
    country === "US" ? 0.17 : country === "CA" ? 0.15 : 0.13;
  return Number((base + ((hash % 7) - 3) * 0.005).toFixed(3));
}

async function fetchEiaRateUsdPerKwh(state: string) {
  const apiKey = process.env.EIA_API_KEY;
  if (!apiKey) return null;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);

  const params = new URLSearchParams({
    frequency: "monthly",
    "data[0]": "price",
    "facets[stateid][]": state,
    "facets[sectorid][]": "RES",
    "sort[0][column]": "period",
    "sort[0][direction]": "desc",
    offset: "0",
    length: "1",
    api_key: apiKey
  });

  try {
    const response = await fetch(
      `https://api.eia.gov/v2/electricity/retail-sales/data/?${params.toString()}`,
      {
        cache: "no-store",
        signal: controller.signal
      }
    );
    if (!response.ok) return null;

    const payload = (await response.json()) as {
      response?: { data?: Array<{ price?: string | number }> };
    };
    const rawPrice = payload.response?.data?.[0]?.price;
    const numeric = Number(rawPrice);
    if (!Number.isFinite(numeric) || numeric <= 0) return null;

    // EIA retail sales price is typically reported in cents/kWh.
    const usdPerKwh = numeric > 1 ? numeric / 100 : numeric;
    return Number(usdPerKwh.toFixed(3));
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const airport = (searchParams.get("airport") ?? "CYKF").slice(0, 4).toUpperCase();
  const date = searchParams.get("date") ?? new Date().toISOString().slice(0, 10);
  const energyKwh = Number(searchParams.get("energyKwh") ?? 52);

  const airportMeta = AIRPORTS[airport];
  if (!airportMeta) {
    return NextResponse.json(
      { error: `Unsupported airport code ${airport}` },
      { status: 400 }
    );
  }

  let liveRate: number | null = null;
  if (airportMeta.country === "US") {
    liveRate = await fetchEiaRateUsdPerKwh(airportMeta.state);
  }

  const costPerKwhUsd =
    liveRate ?? fallbackRateUsdPerKwh(airportMeta.state, airportMeta.country);
  const estimatePayload = ChargingCostResponseSchema.parse({
    estimate: {
      airport,
      state: airportMeta.state,
      costPerKwhUsd,
      estimatedSessionCostUsd: Number((costPerKwhUsd * energyKwh).toFixed(2)),
      energyKwh,
      sourceMode: liveRate ? "live" : "fallback",
      generatedAt: new Date(`${date}T00:00:00Z`).toISOString()
    }
  });

  return NextResponse.json(estimatePayload);
}
