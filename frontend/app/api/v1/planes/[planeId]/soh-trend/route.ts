import { NextResponse } from "next/server";
import { subDays } from "date-fns";

import { SohTrendResponseSchema } from "@/lib/contracts/schemas";
import { readPlaneTrendSnapshot } from "@/lib/snapshot-store";

const WINDOW_DAYS: Record<"30d" | "90d" | "1y", number> = {
  "30d": 30,
  "90d": 90,
  "1y": 365
};

export async function GET(
  request: Request,
  { params }: { params: Promise<{ planeId: string }> }
) {
  const { planeId } = await params;
  const { searchParams } = new URL(request.url);
  const window = (searchParams.get("window") ?? "90d") as "30d" | "90d" | "1y";
  const selectedWindow = WINDOW_DAYS[window] ? window : "90d";

  const data = await readPlaneTrendSnapshot(planeId);
  const cutoff = subDays(new Date(), WINDOW_DAYS[selectedWindow]);
  const points = data.points.filter((point) => {
    const value = point as { date: string };
    return new Date(value.date) >= cutoff;
  });

  const payload = SohTrendResponseSchema.parse({
    planeId,
    window: selectedWindow,
    points
  });

  return NextResponse.json(payload);
}

