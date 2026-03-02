import { NextResponse } from "next/server";

import { GlossaryResponseSchema } from "@/lib/contracts/schemas";
import { readGlossarySnapshot } from "@/lib/snapshot-store";

export async function GET() {
  const data = await readGlossarySnapshot();
  const payload = GlossaryResponseSchema.parse(data);
  return NextResponse.json(payload);
}

