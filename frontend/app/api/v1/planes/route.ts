import { NextResponse } from "next/server";

import { PlanesResponseSchema } from "@/lib/contracts/schemas";
import { readPlanesSnapshot } from "@/lib/mock-store";

export async function GET() {
  const data = await readPlanesSnapshot();
  const parsed = PlanesResponseSchema.parse(data);
  return NextResponse.json(parsed);
}
