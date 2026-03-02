"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { getPlanes } from "@/lib/adapters/api-client";
import { formatPct } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { InfoTooltip } from "@/components/ui/info-tooltip";

function healthFromRisk(riskBand: "low" | "medium" | "high") {
  if (riskBand === "low") return { label: "Healthy", tone: "ok" as const };
  if (riskBand === "medium") return { label: "Watch", tone: "warn" as const };
  return { label: "Critical", tone: "risk" as const };
}

export function PlaneIndex() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["planes"],
    queryFn: getPlanes
  });

  if (isLoading) {
    return <div className="text-sm text-slate-300">Loading fleet...</div>;
  }
  if (isError || !data) {
    return <div className="text-sm text-rose-300">Failed to load fleet snapshots.</div>;
  }

  return (
    <main className="space-y-5">
      <section>
        <h1 className="font-[var(--font-heading)] text-3xl">Fleet Planes</h1>
        <p className="text-sm text-slate-300">
          Monitor live battery health and jump into per-plane operational intelligence.
        </p>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.planes.map((plane) => {
          const health = healthFromRisk(plane.riskBand);
          return (
          <Card key={plane.planeId} className="space-y-4">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-400">Plane {plane.planeId}</p>
                <h2 className="font-[var(--font-heading)] text-xl">{plane.registration}</h2>
              </div>
              <Badge tone={health.tone}>
                {health.label}
              </Badge>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-slate-400">
                  SOH{" "}
                  <InfoTooltip
                    term="SOH"
                    plainLanguage="Battery health compared to new condition."
                    whyItMatters="Lower SOH can reduce flight endurance."
                  />
                </p>
                <p className="font-semibold">{formatPct(plane.sohCurrent)}</p>
              </div>
              <div>
                <p className="text-slate-400">
                  30d Trend{" "}
                  <InfoTooltip
                    term="Trend Points"
                    plainLanguage="How SOH changed in the last 30 days."
                    whyItMatters="Negative points mean wear progression."
                  />
                </p>
                <p className="font-semibold">{plane.sohTrend30.toFixed(2)} pts</p>
              </div>
              <div>
                <p className="text-slate-400">Flights</p>
                <p className="font-semibold">{plane.flightsCount}</p>
              </div>
              <div>
                <p className="text-slate-400">Charging Events</p>
                <p className="font-semibold">{plane.chargingEventsCount}</p>
              </div>
            </div>
            <Link href={`/planes/${plane.planeId}`} className="inline-flex items-center text-sm text-cyan-300 hover:text-cyan-200">
              Open Dashboard <ArrowUpRight className="ml-1 h-4 w-4" />
            </Link>
          </Card>
          );
        })}
      </section>
    </main>
  );
}
