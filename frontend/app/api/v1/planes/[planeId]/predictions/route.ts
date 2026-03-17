import { NextResponse } from "next/server";

import { PredictionsResponseSchema } from "@/lib/contracts/schemas";
import { getLivePredictionPayload } from "@/lib/live-prediction-service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ planeId: string }> }
) {
  const { planeId } = await params;
  const live = await getLivePredictionPayload(planeId);
  const payload = PredictionsResponseSchema.parse(live);
  return NextResponse.json(payload);
}

