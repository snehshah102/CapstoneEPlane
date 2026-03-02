import { NextResponse } from "next/server";

import { RecommendationsResponseSchema } from "@/lib/contracts/schemas";
import { readPlaneRecommendationsSnapshot } from "@/lib/snapshot-store";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ planeId: string }> }
) {
  const { planeId } = await params;
  const { searchParams } = new URL(request.url);
  const month = searchParams.get("month") ?? new Date().toISOString().slice(0, 7);

  const data = await readPlaneRecommendationsSnapshot(planeId, month);
  const payload = RecommendationsResponseSchema.parse(data);
  return NextResponse.json(payload);
}

