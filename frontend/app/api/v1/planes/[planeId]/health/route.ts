import { NextResponse } from "next/server";

import { PlaneHealthResponseSchema } from "@/lib/contracts/schemas";
import { readPlaneKpisSnapshot } from "@/lib/mock-store";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ planeId: string }> }
) {
  const { planeId } = await params;
  const data = await readPlaneKpisSnapshot(planeId);
  const parsed = PlaneHealthResponseSchema.parse({ health: data.health });
  return NextResponse.json(parsed);
}
