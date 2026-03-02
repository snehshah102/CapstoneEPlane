"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowUpRight,
  BatteryCharging,
  CalendarRange,
  CircleHelp,
  PlaneTakeoff
} from "lucide-react";

import {
  getGlossary,
  getPlaneRecommendations,
  getPlanes
} from "@/lib/adapters/api-client";
import { GLOSSARY_FALLBACK } from "@/lib/glossary";
import { formatPct } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { GlossaryDrawer } from "@/components/ui/glossary-drawer";
import { InfoTooltip } from "@/components/ui/info-tooltip";

function currentMonth() {
  return new Date().toISOString().slice(0, 7);
}

export function HomepageShell() {
  const [selectedGlossaryId, setSelectedGlossaryId] = useState<string | null>(
    "soh"
  );

  const planesQuery = useQuery({
    queryKey: ["planes"],
    queryFn: getPlanes
  });

  const primaryPlaneId = planesQuery.data?.planes[0]?.planeId;
  const recsQuery = useQuery({
    queryKey: ["plane-recs-home", primaryPlaneId, currentMonth()],
    queryFn: () => getPlaneRecommendations(primaryPlaneId!, currentMonth()),
    enabled: Boolean(primaryPlaneId)
  });

  const glossaryQuery = useQuery({
    queryKey: ["glossary"],
    queryFn: getGlossary
  });

  const glossaryItems = useMemo(
    () => glossaryQuery.data?.items ?? GLOSSARY_FALLBACK,
    [glossaryQuery.data?.items]
  );

  if (planesQuery.isLoading) {
    return <div className="text-sm text-slate-300">Loading experience...</div>;
  }
  if (planesQuery.isError || !planesQuery.data) {
    return <div className="text-sm text-rose-300">Could not load fleet snapshots.</div>;
  }

  return (
    <main className="space-y-8 pb-28">
      <section className="glass rounded-3xl p-7 md:p-10">
        <div className="mb-5 rounded-xl border border-slate-600/35 bg-slate-950/25 p-4 text-sm text-slate-300">
          <p className="mb-2 inline-flex items-center gap-2 font-semibold text-slate-100">
            <CircleHelp size={16} />
            How to read this page
          </p>
          <p>
            This is a guided overview for students. If a metric is unfamiliar, use
            the info icon next to it or open the pinned glossary.
          </p>
        </div>
        <div className="relative grid gap-8 lg:grid-cols-12">
          <div className="space-y-5 lg:col-span-7">
            <p className="inline-flex items-center gap-2 rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-xs text-cyan-200">
              <BatteryCharging size={14} />
              Experience Overview
            </p>
            <h1 className="font-[var(--font-heading)] text-3xl leading-tight md:text-5xl">
              See battery health intelligence without needing battery expertise.
            </h1>
            <p className="max-w-xl text-sm text-slate-300 md:text-base">
              We combine telemetry, model predictions, and recommendation logic so
              students can quickly understand what is happening and why.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Link href="/planes">
                <Button className="gap-2">
                  Open Plane Dashboards
                  <ArrowUpRight size={16} />
                </Button>
              </Link>
              <Link href="/learn">
                <Button className="bg-slate-100 text-slate-900 hover:bg-white">
                  Try the Learn Simulator
                </Button>
              </Link>
            </div>
          </div>
          <div className="glass rounded-2xl p-5 lg:col-span-5">
            <p className="text-sm text-slate-100">Section subtitle</p>
            <p className="text-xs text-slate-400">
              At-a-glance reliability and wear direction.
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
              <button
                type="button"
                onClick={() => setSelectedGlossaryId("confidence")}
                className="rounded-lg border border-slate-600/30 p-3 text-left"
              >
                <p className="text-slate-400">
                  Forecast Confidence{" "}
                  <InfoTooltip
                    term="Confidence"
                    plainLanguage="How sure the model is about this prediction."
                    whyItMatters="Higher confidence means recommendation trust is stronger."
                  />
                </p>
                <p className="mt-1 text-lg font-semibold text-emerald-300">0.86</p>
              </button>
              <button
                type="button"
                onClick={() => setSelectedGlossaryId("rul")}
                className="rounded-lg border border-slate-600/30 p-3 text-left"
              >
                <p className="text-slate-400">
                  RUL Tracking{" "}
                  <InfoTooltip
                    term="RUL"
                    plainLanguage="Estimated life left before replacement is advised."
                    whyItMatters="Helps you plan maintenance before battery health becomes critical."
                  />
                </p>
                <p className="mt-1 text-lg font-semibold text-cyan-300">On Target</p>
              </button>
            </div>
          </div>
        </div>
      </section>

      <section>
        <p className="text-xs uppercase tracking-wide text-slate-400">Fleet Snapshot</p>
        <h2 className="font-[var(--font-heading)] text-2xl">What each plane looks like right now</h2>
        <p className="text-sm text-slate-300">
          Subtitle: SOH and trend values are updated from the latest processed data.
        </p>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        {planesQuery.data.planes.map((plane) => (
          <Card key={plane.planeId} className="animate-rise-in space-y-4">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-400">Plane {plane.planeId}</p>
                <h3 className="font-[var(--font-heading)] text-xl">{plane.registration}</h3>
              </div>
              <Badge tone={plane.riskBand === "low" ? "ok" : plane.riskBand === "medium" ? "warn" : "risk"}>
                {plane.riskBand.toUpperCase()}
              </Badge>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <button
                type="button"
                onClick={() => setSelectedGlossaryId("soh")}
                className="text-left"
              >
                <p className="text-slate-400">
                  SOH{" "}
                  <InfoTooltip
                    term="SOH"
                    plainLanguage="Battery health compared to new condition."
                    whyItMatters="Lower SOH can reduce flight endurance."
                  />
                </p>
                <p className="text-lg font-semibold">{formatPct(plane.sohCurrent)}</p>
              </button>
              <button
                type="button"
                onClick={() => setSelectedGlossaryId("trend_points")}
                className="text-left"
              >
                <p className="text-slate-400">
                  30d Trend{" "}
                  <InfoTooltip
                    term="Trend Points"
                    plainLanguage="How much SOH has changed in the last 30 days."
                    whyItMatters="Negative values indicate wear progression."
                  />
                </p>
                <p className="text-lg font-semibold">{plane.sohTrend30.toFixed(2)} pts</p>
              </button>
            </div>
            <Link href={`/planes/${plane.planeId}`} className="inline-flex items-center text-sm text-cyan-300 hover:text-cyan-200">
              View Plane Dashboard <ArrowUpRight className="ml-1 h-4 w-4" />
            </Link>
          </Card>
        ))}
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.25fr_0.75fr]">
        <Card className="space-y-4">
          <div className="flex items-center gap-2">
            <CalendarRange size={16} className="text-cyan-300" />
            <h3 className="font-[var(--font-heading)] text-lg">Best Days to Fly This Month</h3>
          </div>
          <p className="text-xs text-slate-400">
            Subtitle: Scores rank each day for battery-friendly operations using weather and wear factors.
          </p>
          <div className="grid gap-2 md:grid-cols-2">
            {recsQuery.data?.recommendations.flightDayScores.slice(0, 6).map((day) => (
              <button
                type="button"
                key={day.date}
                onClick={() => setSelectedGlossaryId("calendar_score")}
                className="rounded-xl border border-slate-600/30 p-3 text-left text-sm"
              >
                <div className="flex items-center justify-between">
                  <p>{day.date}</p>
                  <Badge
                    tone={
                      day.confidenceTier === "high"
                        ? "ok"
                        : day.confidenceTier === "medium"
                          ? "warn"
                          : "risk"
                    }
                    className="capitalize"
                  >
                    {day.confidenceTier}
                  </Badge>
                </div>
                <p className="mt-1 font-semibold text-cyan-200">Score {day.score.toFixed(1)}</p>
                <p className="text-xs text-slate-400">{day.weatherSummary}</p>
              </button>
            ))}
          </div>
        </Card>

        <Card className="space-y-4">
          <div className="flex items-center gap-2">
            <PlaneTakeoff size={16} className="text-emerald-300" />
            <h3 className="font-[var(--font-heading)] text-lg">Why these sections exist</h3>
          </div>
          <ol className="space-y-2 text-sm text-slate-300">
            <li>1. Battery health explains current condition.</li>
            <li>2. Trend explains wear direction over time.</li>
            <li>3. Calendar explains the best day to fly and why.</li>
            <li>4. Charge timing explains how to reduce avoidable wear.</li>
          </ol>
        </Card>
      </section>

      <GlossaryDrawer
        items={glossaryItems}
        selectedId={selectedGlossaryId}
        title="Student Glossary"
      />
    </main>
  );
}
