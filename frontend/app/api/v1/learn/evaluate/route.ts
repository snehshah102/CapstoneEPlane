import { NextResponse } from "next/server";

import { LearnEvaluateRequestSchema } from "@/lib/contracts/schemas";
import { evaluateLearnScenario } from "@/lib/live-learn-service";

export async function POST(request: Request) {
  const body = await request.json();
  const input = LearnEvaluateRequestSchema.parse(body);
  const payload = await evaluateLearnScenario(input.planeId, input.inputs);
  return NextResponse.json(payload);
}
