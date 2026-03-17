import { NextResponse } from "next/server";

import { PredictionsResponseSchema } from "@/lib/contracts/schemas";
import { getLivePlanePayload } from "@/lib/live-plane-service";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ planeId: string }> }
) {
  const { planeId } = await params;
  const live = await getLivePlanePayload(planeId);
  const payload = PredictionsResponseSchema.parse({ prediction: live.prediction });
  return NextResponse.json(payload);
}

