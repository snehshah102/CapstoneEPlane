import { NextResponse } from "next/server";

import { getMissionGameBaselinePayload } from "@/lib/mission-game-baseline";

export async function GET() {
  return NextResponse.json(await getMissionGameBaselinePayload());
}
