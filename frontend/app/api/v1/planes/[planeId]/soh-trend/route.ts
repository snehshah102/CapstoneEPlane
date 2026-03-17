import { NextResponse } from "next/server";
import { subDays } from "date-fns";

import { SohTrendResponseSchema } from "@/lib/contracts/schemas";
import { getLivePlanePayload } from "@/lib/live-plane-service";

type TrendWindow = "30d" | "90d" | "1y" | "full";
export const dynamic = "force-dynamic";
export const revalidate = 0;

const WINDOW_DAYS: Record<Exclude<TrendWindow, "full">, number> = {
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
  const window = (searchParams.get("window") ?? "90d") as TrendWindow;
  const selectedWindow: TrendWindow =
    window === "30d" || window === "90d" || window === "1y" || window === "full"
      ? window
      : "90d";

  const live = await getLivePlanePayload(planeId);
  const data =
    Array.isArray(live.history?.points) && live.history.points.length > 0
      ? live.history
      : live.trend;

  const allPoints = (data.points as Array<{ date: string; soh: number; source: string }>)
    .filter((point) => Number.isFinite(Date.parse(point.date)))
    .sort((a, b) => Date.parse(a.date) - Date.parse(b.date));

  let points = allPoints;
  if (allPoints.length > 0 && selectedWindow !== "full") {
    const latestDate = new Date(allPoints[allPoints.length - 1].date);
    const cutoff = subDays(latestDate, WINDOW_DAYS[selectedWindow]);
    const windowed = allPoints.filter((point) => new Date(point.date) >= cutoff);
    points = windowed.length > 0 ? windowed : allPoints.slice(-Math.min(60, allPoints.length));
  }

  const payload = SohTrendResponseSchema.parse({
    planeId,
    window: selectedWindow,
    points
  });

  return NextResponse.json(payload);
}
