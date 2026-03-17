import { NextResponse } from "next/server";

import { PlanesResponseSchema } from "@/lib/contracts/schemas";
import { getLivePlanesPayload } from "@/lib/live-plane-summaries";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const data = await getLivePlanesPayload();
  const parsed = PlanesResponseSchema.parse(data);
  return NextResponse.json(parsed);
}
