import { NextResponse } from "next/server";

import { GlossaryResponseSchema } from "@/lib/contracts/schemas";
import { GLOSSARY_FALLBACK } from "@/lib/glossary";

export async function GET() {
  const payload = GlossaryResponseSchema.parse({
    version: "codebase_fallback_v1",
    items: GLOSSARY_FALLBACK
  });
  return NextResponse.json(payload);
}

