import { NextResponse } from "next/server";

import { MissionGameBaselineResponseSchema } from "@/lib/contracts/schemas";

export async function GET() {
  const today = new Date().toISOString().slice(0, 10);
  const payload = MissionGameBaselineResponseSchema.parse({
    baseline: {
      defaults: {
        date: today,
        plannedDurationMin: 55,
        routeDistanceKm: 120,
        targetSoc: 82,
        payloadLevel: "medium",
        weatherMode: "forecast",
        manualWeather: {
          tempC: 21,
          windKph: 14,
          precipMm: 0.8
        }
      },
      scoringWeights: {
        battery: 0.45,
        safety: 0.35,
        cost: 0.2,
        version: "mission_game_v1"
      }
    }
  });

  return NextResponse.json(payload);
}
