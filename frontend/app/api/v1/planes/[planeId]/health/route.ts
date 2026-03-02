import { NextResponse } from "next/server";

import { PlaneHealthResponseSchema } from "@/lib/contracts/schemas";
import { readPlaneKpisSnapshot } from "@/lib/snapshot-store";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ planeId: string }> }
) {
  const { planeId } = await params;
  const data = await readPlaneKpisSnapshot(planeId);
  const rawHealth = data.health as {
    updatedAt?: string;
    pack?: { soc?: number };
    currentChargeSoc?: number;
    timeSinceLastFlightHours?: number;
    lastFlight?: { eventDate?: string };
  };

  const flightTime = rawHealth.lastFlight?.eventDate
    ? new Date(`${rawHealth.lastFlight.eventDate}T00:00:00Z`)
    : new Date(rawHealth.updatedAt ?? new Date().toISOString());
  const elapsedHours = Math.max(
    0,
    Math.round((Date.now() - flightTime.getTime()) / 3_600_000)
  );

  const enrichedHealth = {
    ...rawHealth,
    currentChargeSoc: rawHealth.currentChargeSoc ?? rawHealth.pack?.soc ?? 0,
    timeSinceLastFlightHours:
      rawHealth.timeSinceLastFlightHours ?? elapsedHours
  };

  const parsed = PlaneHealthResponseSchema.parse({ health: enrichedHealth });
  return NextResponse.json(parsed);
}

