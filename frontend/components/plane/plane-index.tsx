"use client";

import Image from "next/image";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowUpRight, BatteryCharging, Cpu, GaugeCircle, Wind } from "lucide-react";

import { getPlanes } from "@/lib/adapters/api-client";
import { ELECTRIC_PLANE_MEDIA } from "@/lib/electric-plane-media";
import type { PlaneSummary } from "@/lib/contracts/schemas";
import { formatPct } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { InfoTooltip } from "@/components/ui/info-tooltip";

function healthFromRisk(
  riskBand: "low" | "medium" | "watch" | "critical" | "decline" | "high"
) {
  if (riskBand === "low") return { label: "Healthy", tone: "ok" as const };
  if (riskBand === "medium") return { label: "Medium", tone: "warn" as const };
  if (riskBand === "watch") return { label: "Watch", tone: "risk" as const };
  if (riskBand === "decline") return { label: "Watch", tone: "risk" as const };
  if (riskBand === "high") return { label: "Watch", tone: "risk" as const };
  return { label: "Critical", tone: "risk" as const };
}

const PLANE_PARTS = {
  battery: {
    label: "Battery Pack",
    short: "Energy storage",
    detail:
      "High-density battery modules store propulsion energy. State of Health (SOH), charge target, and time at high SOC strongly influence cycle life.",
    accent: "from-blue-600 to-cyan-500",
    image: ELECTRIC_PLANE_MEDIA.battery.src,
    imageAlt: ELECTRIC_PLANE_MEDIA.battery.alt,
    imagePosition: "47% 44%",
    metrics: ["Watch SOH decline", "Limit high-SOC dwell", "Charge closer to departure"],
    icon: BatteryCharging,
    sourceHref: ELECTRIC_PLANE_MEDIA.battery.creditHref,
    sourceLabel: ELECTRIC_PLANE_MEDIA.battery.creditLabel,
    overview:
      "Battery architecture, charge targets, and dwell time at high SOC determine how much usable life is preserved between training cycles."
  },
  prop: {
    label: "Electric Motor + Propeller",
    short: "Powertrain",
    detail:
      "The motor converts battery power into thrust. Aggressive power demand, repeated high-thrust climbs, and thermal load affect wear rate.",
    accent: "from-sky-600 to-indigo-600",
    image: ELECTRIC_PLANE_MEDIA.engine.src,
    imageAlt: ELECTRIC_PLANE_MEDIA.engine.alt,
    imagePosition: "54% 45%",
    metrics: ["Track thermal load", "Limit repeated full-power climbs", "Monitor power spikes"],
    icon: GaugeCircle,
    sourceHref: ELECTRIC_PLANE_MEDIA.engine.creditHref,
    sourceLabel: ELECTRIC_PLANE_MEDIA.engine.creditLabel,
    overview:
      "Motor output and propeller demand drive instantaneous load on the pack, especially during climb-heavy training or repeated short sorties."
  },
  wing: {
    label: "Wing + Aerodynamics",
    short: "Efficiency",
    detail:
      "Lift efficiency changes energy required per mission. More efficient aerodynamic performance reduces battery strain for the same route.",
    accent: "from-emerald-600 to-teal-500",
    image: ELECTRIC_PLANE_MEDIA.wing.src,
    imageAlt: ELECTRIC_PLANE_MEDIA.wing.alt,
    imagePosition: "50% 42%",
    metrics: ["Watch wind penalties", "Reduce drag-heavy mission choices", "Protect endurance margin"],
    icon: Wind,
    sourceHref: ELECTRIC_PLANE_MEDIA.wing.creditHref,
    sourceLabel: ELECTRIC_PLANE_MEDIA.wing.creditLabel,
    overview:
      "Aerodynamic efficiency changes how much energy is required per route. Wind, climb profile, and aircraft drag all affect daily endurance margin."
  },
  avionics: {
    label: "Avionics + Telemetry",
    short: "Data system",
    detail:
      "Flight and battery telemetry streams into the analytics pipeline used for trend tracking, replacement forecasting, and recommendation generation.",
    accent: "from-violet-600 to-fuchsia-500",
    image: ELECTRIC_PLANE_MEDIA.avionics.src,
    imageAlt: ELECTRIC_PLANE_MEDIA.avionics.alt,
    imagePosition: "50% 35%",
    metrics: ["Keep event timing clean", "Preserve sensor quality", "Improve model confidence"],
    icon: Cpu,
    sourceHref: ELECTRIC_PLANE_MEDIA.avionics.creditHref,
    sourceLabel: ELECTRIC_PLANE_MEDIA.avionics.creditLabel,
    overview:
      "Reliable cockpit and telemetry signals improve model confidence, explain trend changes, and keep aircraft-level recommendations trustworthy."
  }
} as const;

type PartKey = keyof typeof PLANE_PARTS;

type PlaneIndexProps = {
  initialPlanes?: PlaneSummary[];
};

export function PlaneIndex({ initialPlanes }: PlaneIndexProps) {
  const [activePart, setActivePart] = useState<PartKey>("battery");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["planes"],
    queryFn: getPlanes,
    initialData: initialPlanes ? { planes: initialPlanes } : undefined,
    staleTime: 60_000
  });

  const selectedPart = useMemo(() => PLANE_PARTS[activePart], [activePart]);

  if (isLoading) {
    return <div className="text-sm text-muted">Loading fleet...</div>;
  }
  if ((isError && !data) || !data) {
    return <div className="text-sm text-rose-600">Failed to load fleet data.</div>;
  }

  return (
    <main className="space-y-8">
      <section className="space-y-2">
        <h1 className="section-title text-slate-900">Electric Plane Explorer</h1>
        <p className="text-sm text-muted">
          Explore how energy storage, propulsion, aerodynamics, and telemetry each shape battery
          wear, endurance, and day-to-day operating margin.
        </p>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.48fr_0.52fr]">
        <Card className="space-y-4 p-5">
          <div className="grid gap-2 xl:grid-cols-4">
            {(Object.keys(PLANE_PARTS) as PartKey[]).map((part) => {
              const partInfo = PLANE_PARTS[part];
              const Icon = partInfo.icon;
              const isActive = activePart === part;

              return (
                <button
                  key={part}
                  type="button"
                  onClick={() => setActivePart(part)}
                  className={`inline-flex min-h-11 w-full items-center justify-center gap-2 whitespace-nowrap rounded-full border px-3 py-2 text-[13px] transition duration-200 ${
                    isActive
                      ? "border-blue-500 bg-blue-50 text-blue-800 shadow-sm"
                      : "border-slate-200 bg-white text-slate-700 hover:-translate-y-0.5 hover:border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  <Icon size={16} />
                  {partInfo.label}
                </button>
              );
            })}
          </div>
          <div className="grid gap-4 lg:grid-cols-[1.18fr_0.82fr]">
            <div className="overflow-hidden rounded-[24px] border border-slate-200 bg-white">
              <div className="relative aspect-[16/10]">
                <Image
                  src={selectedPart.image}
                  alt={selectedPart.imageAlt}
                  fill
                  priority
                  sizes="(max-width: 1280px) 100vw, 55vw"
                  className="object-cover"
                  style={{ objectPosition: selectedPart.imagePosition }}
                />
                <div className="absolute inset-0 bg-gradient-to-t from-slate-950/14 to-transparent" />
              </div>
              <div className="border-t border-slate-200 bg-slate-50 px-4 py-3">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Airframe Context
                </p>
                <p className="mt-1 text-sm text-slate-600">{selectedPart.overview}</p>
              </div>
            </div>

            <div className="rounded-[24px] border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-slate-100 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Selected System</p>
              <h2 className="mt-2 font-[var(--font-heading)] text-3xl text-slate-900">
                {selectedPart.label}
              </h2>
              <p
                className={`mt-3 inline-flex rounded-full bg-gradient-to-r ${selectedPart.accent} px-3 py-1.5 text-xs font-semibold text-white`}
              >
                {selectedPart.short}
              </p>
              <p className="mt-4 text-sm leading-relaxed text-slate-700">{selectedPart.detail}</p>
              <div className="mt-5 grid gap-2">
                {selectedPart.metrics.map((metric) => (
                  <div
                    key={metric}
                    className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700"
                  >
                    {metric}
                  </div>
                ))}
              </div>
              <a
                href={selectedPart.sourceHref}
                target="_blank"
                rel="noreferrer"
                className="mt-5 inline-block text-xs text-slate-500 underline-offset-4 hover:text-slate-700 hover:underline"
              >
                Image source: {selectedPart.sourceLabel}
              </a>
            </div>
          </div>
        </Card>

        <Card className="self-start space-y-4 p-5">
          <div>
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Quick Select</p>
            <h3 className="mt-1 font-[var(--font-heading)] text-2xl text-slate-900">
              Explore another system
            </h3>
          </div>
          <div className="grid gap-2">
            {(Object.keys(PLANE_PARTS) as PartKey[]).map((part) => (
              <button
                key={part}
                type="button"
                onClick={() => setActivePart(part)}
                className={`rounded-2xl border px-3 py-3 text-left text-sm transition duration-200 ${
                  activePart === part
                    ? "border-blue-500 bg-blue-50 text-blue-800 shadow-sm"
                    : "border-slate-200 bg-white text-slate-700 hover:-translate-y-0.5 hover:border-slate-300 hover:bg-slate-50"
                }`}
              >
                <p className="font-medium">{PLANE_PARTS[part].label}</p>
                <p className="mt-1 text-xs text-slate-500">{PLANE_PARTS[part].short}</p>
              </button>
            ))}
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
            Choose a system to see how it affects endurance, wear rate, operating margin,
            and the quality of the data feeding aircraft-level recommendations.
          </div>
        </Card>
      </section>

      <section className="grid gap-5 md:grid-cols-2">
        {data.planes.map((plane) => {
          const health = healthFromRisk(plane.riskBand);
          return (
            <Card key={plane.planeId} className="space-y-5 p-7">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted">
                    Plane {plane.planeId}
                  </p>
                  <h2 className="font-[var(--font-heading)] text-3xl text-slate-900">
                    {plane.registration}
                  </h2>
                </div>
                <Badge tone={health.tone}>{health.label}</Badge>
              </div>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-muted">
                    SOH{" "}
                    <InfoTooltip
                      term="SOH"
                      plainLanguage="Battery health compared to new condition."
                      whyItMatters="Lower SOH can reduce expected flight endurance."
                    />
                  </p>
                  <p className="text-xl font-semibold text-slate-900">
                    {formatPct(plane.sohCurrent)}
                  </p>
                </div>
                <div>
                  <p className="text-muted">
                    30d Trend{" "}
                    <InfoTooltip
                      term="Trend Points"
                      plainLanguage="Change in SOH across the last 30 days."
                      whyItMatters="Negative points indicate wear progression."
                    />
                  </p>
                  <p className="text-xl font-semibold text-slate-900">
                    {plane.sohTrend30.toFixed(2)} pts
                  </p>
                </div>
                <div>
                  <p className="text-muted">Flights</p>
                  <p className="text-xl font-semibold text-slate-900">{plane.flightsCount}</p>
                </div>
                <div>
                  <p className="text-muted">Charging Events</p>
                  <p className="text-xl font-semibold text-slate-900">
                    {plane.chargingEventsCount}
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-4">
                <Link
                  href={`/planes/${plane.planeId}`}
                  className="inline-flex items-center text-base font-medium text-blue-700 hover:text-blue-600"
                >
                  Open Plane Dashboard <ArrowUpRight className="ml-1 h-4 w-4" />
                </Link>
                <Link
                  href="/mission-game"
                  className="inline-flex items-center text-sm font-medium text-slate-700 hover:text-slate-900"
                >
                  Open FlightLab <ArrowUpRight className="ml-1 h-4 w-4" />
                </Link>
              </div>
            </Card>
          );
        })}
      </section>
    </main>
  );
}
