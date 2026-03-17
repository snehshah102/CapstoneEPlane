import { addDays } from "date-fns";
import { NextResponse } from "next/server";

import { getWeatherPayload } from "@/lib/weather-service";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const airport = (searchParams.get("airport") ?? "CYKF").toUpperCase();
  const start = searchParams.get("start") ?? new Date().toISOString().slice(0, 10);
  const end = searchParams.get("end") ?? addDays(new Date(), 30).toISOString().slice(0, 10);

  try {
    const payload = await getWeatherPayload(airport, start, end);
    return NextResponse.json(payload);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : `Unsupported airport code ${airport}` },
      { status: 400 }
    );
  }
}
