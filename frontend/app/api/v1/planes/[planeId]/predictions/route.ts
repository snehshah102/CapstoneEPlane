import { NextResponse } from "next/server";

import { PredictionsResponseSchema } from "@/lib/contracts/schemas";
import { readPlaneKpisSnapshot } from "@/lib/mock-store";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ planeId: string }> }
) {
  const { planeId } = await params;
  const data = await readPlaneKpisSnapshot(planeId);
  const payload = PredictionsResponseSchema.parse({ prediction: data.prediction });
  return NextResponse.json(payload);
}
