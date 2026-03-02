import { NextResponse } from "next/server";

import { LearnBaselineResponseSchema } from "@/lib/contracts/schemas";
import { readLearnBaselineSnapshot } from "@/lib/snapshot-store";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const planeId = searchParams.get("planeId") ?? "166";
  const data = await readLearnBaselineSnapshot(planeId);
  const payload = LearnBaselineResponseSchema.parse(data);
  return NextResponse.json(payload);
}

