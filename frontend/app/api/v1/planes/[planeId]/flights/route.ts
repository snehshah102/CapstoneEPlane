import { NextResponse } from "next/server";

import { FlightsResponseSchema } from "@/lib/contracts/schemas";
import { getLivePlanePayload } from "@/lib/live-plane-service";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ planeId: string }> }
) {
  const { planeId } = await params;
  const { searchParams } = new URL(request.url);
  const limit = Number(searchParams.get("limit") ?? 25);

  const live = await getLivePlanePayload(planeId);
  const data = live.flights;
  const payload = FlightsResponseSchema.parse({
    planeId,
    flights: data.flights.slice(0, Math.max(1, limit))
  });

  return NextResponse.json(payload);
}

