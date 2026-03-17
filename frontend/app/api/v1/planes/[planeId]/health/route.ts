import { NextResponse } from "next/server";

import { PlaneHealthResponseSchema } from "@/lib/contracts/schemas";
import {
  healthExplanationFromLabel,
  healthLabelFromRiskBand,
  riskBandFromSoh
} from "@/lib/soh-health-bands";
import { getLivePlanePayload } from "@/lib/live-plane-service";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ planeId: string }> }
) {
  const { planeId } = await params;
  const live = await getLivePlanePayload(planeId);
  const rawHealth = live.health as {
    updatedAt?: string;
    pack?: { soc?: number };
    currentChargeSoc?: number;
    timeSinceLastFlightHours?: number;
    lastFlight?: {
      eventDate?: string;
      route?: string | null;
      departureAirport?: string | null;
      destinationAirport?: string | null;
      durationMin?: number | null;
      flightId?: number;
      eventType?: string;
    };
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
    lastFlight: {
      flightId: rawHealth.lastFlight?.flightId ?? 0,
      eventDate:
        rawHealth.lastFlight?.eventDate ??
        new Date(rawHealth.updatedAt ?? Date.now()).toISOString().slice(0, 10),
      route: rawHealth.lastFlight?.route ?? "Unknown route",
      departureAirport: rawHealth.lastFlight?.departureAirport ?? null,
      destinationAirport: rawHealth.lastFlight?.destinationAirport ?? null,
      durationMin: rawHealth.lastFlight?.durationMin ?? null,
      eventType: rawHealth.lastFlight?.eventType ?? "unknown"
    },
    currentChargeSoc: rawHealth.currentChargeSoc ?? rawHealth.pack?.soc ?? 0,
    timeSinceLastFlightHours:
      rawHealth.timeSinceLastFlightHours ?? elapsedHours
  };

  const sohCurrent =
    Number((enrichedHealth as { sohCurrent?: number }).sohCurrent) || 0;
  const normalizedRiskBand = riskBandFromSoh(sohCurrent);
  const normalizedHealthLabel = healthLabelFromRiskBand(normalizedRiskBand);
  const normalizedHealth = {
    ...enrichedHealth,
    riskBand: normalizedRiskBand,
    healthLabel: normalizedHealthLabel,
    healthExplanation: healthExplanationFromLabel(normalizedHealthLabel)
  };

  const parsed = PlaneHealthResponseSchema.parse({ health: normalizedHealth });
  return NextResponse.json(parsed);
}
