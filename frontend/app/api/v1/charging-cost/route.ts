import { NextResponse } from "next/server";

import { getChargingCostEstimatePayload } from "@/lib/charging-cost-service";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const airport = (searchParams.get("airport") ?? "CYKF").slice(0, 4).toUpperCase();
  const date = searchParams.get("date") ?? new Date().toISOString().slice(0, 10);
  const energyKwh = Number(searchParams.get("energyKwh") ?? 52);

  try {
    const payload = await getChargingCostEstimatePayload(airport, date, energyKwh);
    return NextResponse.json(payload);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Charging cost unavailable" },
      { status: 400 }
    );
  }
}
