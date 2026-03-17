import { NextResponse } from "next/server";

import { getLearnBaselinePayload } from "@/lib/live-learn-service";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const planeId = searchParams.get("planeId") ?? "166";
  const payload = await getLearnBaselinePayload(planeId);
  return NextResponse.json(payload);
}

