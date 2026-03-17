import { NextResponse } from "next/server";

import { MissionGameInputSchema } from "@/lib/contracts/schemas";
import { evaluateMissionGameLive } from "@/lib/live-mission-service";

export async function POST(request: Request) {
  const body = await request.json();
  const input = MissionGameInputSchema.parse(body);
  const payload = await evaluateMissionGameLive(input);
  return NextResponse.json(payload);
}
