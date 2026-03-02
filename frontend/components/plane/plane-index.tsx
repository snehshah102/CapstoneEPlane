"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowUpRight, RotateCcw } from "lucide-react";

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

const PLANE_PARTS = {
  battery: {
    label: "Battery Pack",
    short: "Energy storage",
    detail:
      "High-density battery modules store propulsion energy. State of Health (SOH), charge target, and time at high SOC strongly influence cycle life."
  },
  prop: {
    label: "Electric Motor + Propeller",
    short: "Powertrain",
    detail:
      "The motor converts battery power into thrust. Aggressive power demand, repeated high-thrust climbs, and thermal load affect wear rate."
  },
  wing: {
    label: "Wing + Aerodynamics",
    short: "Efficiency",
    detail:
      "Lift efficiency changes energy required per mission. More efficient aerodynamic performance reduces battery strain for the same route."
  },
  avionics: {
    label: "Avionics + Telemetry",
    short: "Data system",
    detail:
      "Flight and battery telemetry streams into the analytics pipeline used for trend tracking, replacement forecasting, and recommendation generation."
  }
} as const;

type PartKey = keyof typeof PLANE_PARTS;

export function PlaneIndex() {
  const [activePart, setActivePart] = useState<PartKey>("battery");
  const [paused, setPaused] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["planes"],
    queryFn: getPlanes
  });

  const selectedPart = useMemo(() => PLANE_PARTS[activePart], [activePart]);

  if (isLoading) {
    return <div className="text-sm text-muted">Loading fleet...</div>;
  }
  if (isError || !data) {
    return <div className="text-sm text-rose-600">Failed to load fleet snapshots.</div>;
  }

  return (
    <main className="space-y-8">
      <section className="space-y-2">
        <h1 className="section-title text-slate-900">Electric Plane Explorer</h1>
        <p className="text-sm text-muted">
          Select any major component on the aircraft to understand how it relates to
          battery health and flight performance.
        </p>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
        <Card className="relative overflow-hidden p-4">
          <div className="absolute right-4 top-4 z-20">
            <button
              type="button"
              onClick={() => setPaused((value) => !value)}
              className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:bg-slate-50"
            >
              {paused ? "Resume Rotation" : "Pause Rotation"}
            </button>
          </div>
          <div className="relative mx-auto max-w-[940px]">
            <div className={`plane-rotate ${paused ? "plane-rotate-paused" : ""}`}>
              <svg viewBox="0 0 900 420" className="h-[390px] w-full">
                <defs>
                  <linearGradient id="fuseGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#ffffff" />
                    <stop offset="100%" stopColor="#dbe9ff" />
                  </linearGradient>
                  <linearGradient id="wingGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#c7d8f8" />
                    <stop offset="100%" stopColor="#89a7e6" />
                  </linearGradient>
                  <filter id="activeGlow">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                </defs>

                <ellipse cx="450" cy="346" rx="285" ry="24" fill="#c6cfde" opacity="0.34" />

                <path
                  d="M120 236 L345 180 L635 171 L764 198 L640 223 L347 235 Z"
                  fill="url(#wingGrad)"
                  stroke={activePart === "wing" ? "#1d4ed8" : "transparent"}
                  strokeWidth={activePart === "wing" ? 4 : 0}
                  filter={activePart === "wing" ? "url(#activeGlow)" : undefined}
                />

                <path
                  d="M205 220 C242 150, 354 120, 520 128 C602 132, 683 154, 742 195 C758 205, 758 222, 742 232 C683 270, 602 292, 518 299 C350 307, 241 271, 205 220Z"
                  fill="url(#fuseGrad)"
                  stroke="#9eb3d8"
                  strokeWidth="2"
                />

                <rect
                  x="310"
                  y="224"
                  width="170"
                  height="34"
                  rx="17"
                  fill={activePart === "battery" ? "#1d4ed8" : "#d7e3fa"}
                  opacity={activePart === "battery" ? 0.9 : 0.75}
                  stroke={activePart === "battery" ? "#0f172a" : "none"}
                  strokeWidth={activePart === "battery" ? 2 : 0}
                  filter={activePart === "battery" ? "url(#activeGlow)" : undefined}
                />

                <circle
                  cx="600"
                  cy="218"
                  r="42"
                  fill="#203f7f"
                  stroke={activePart === "prop" ? "#0ea5e9" : "#1e40af"}
                  strokeWidth={activePart === "prop" ? 7 : 4}
                  filter={activePart === "prop" ? "url(#activeGlow)" : undefined}
                />
                <circle cx="600" cy="218" r="27" fill="#5fa9f4" />
                <circle cx="600" cy="218" r="12" fill="#ecfeff" />

                <rect
                  x="375"
                  y="170"
                  width="82"
                  height="22"
                  rx="11"
                  fill={activePart === "avionics" ? "#0f766e" : "#94a3b8"}
                  stroke={activePart === "avionics" ? "#0f172a" : "none"}
                  strokeWidth={activePart === "avionics" ? 2 : 0}
                  filter={activePart === "avionics" ? "url(#activeGlow)" : undefined}
                />

                <path d="M334 191 L258 132 L346 176 Z" fill="#8fa1c2" />
                <path d="M334 257 L250 318 L368 266 Z" fill="#7f95bc" />
                <path d="M635 171 L720 120 L668 184 Z" fill="#d4e2ff" />
                <path d="M635 234 L725 272 L668 223 Z" fill="#c0d5ff" />
              </svg>
            </div>

            <button
              type="button"
              onClick={() => {
                setActivePart("battery");
                setPaused(true);
              }}
              className={`absolute left-[41%] top-[58%] h-8 w-8 rounded-full border-2 ${
                activePart === "battery"
                  ? "border-blue-700 bg-blue-100 ring-4 ring-blue-200"
                  : "border-blue-500 bg-white/95"
              }`}
              aria-label="Battery pack hotspot"
            />
            <button
              type="button"
              onClick={() => {
                setActivePart("prop");
                setPaused(true);
              }}
              className={`absolute left-[62%] top-[50%] h-8 w-8 rounded-full border-2 ${
                activePart === "prop"
                  ? "border-blue-700 bg-blue-100 ring-4 ring-blue-200"
                  : "border-blue-500 bg-white/95"
              }`}
              aria-label="Powertrain hotspot"
            />
            <button
              type="button"
              onClick={() => {
                setActivePart("wing");
                setPaused(true);
              }}
              className={`absolute left-[50%] top-[41%] h-8 w-8 rounded-full border-2 ${
                activePart === "wing"
                  ? "border-blue-700 bg-blue-100 ring-4 ring-blue-200"
                  : "border-blue-500 bg-white/95"
              }`}
              aria-label="Wing hotspot"
            />
            <button
              type="button"
              onClick={() => {
                setActivePart("avionics");
                setPaused(true);
              }}
              className={`absolute left-[46%] top-[47%] h-8 w-8 rounded-full border-2 ${
                activePart === "avionics"
                  ? "border-blue-700 bg-blue-100 ring-4 ring-blue-200"
                  : "border-blue-500 bg-white/95"
              }`}
              aria-label="Avionics hotspot"
            />
          </div>
        </Card>

        <Card className="space-y-4">
          <p className="text-xs uppercase tracking-wide text-muted">Selected Component</p>
          <h2 className="font-[var(--font-heading)] text-2xl text-slate-900">
            {selectedPart.label}
          </h2>
          <p className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-blue-700">
            {selectedPart.short}
          </p>
          <p className="text-sm leading-relaxed text-slate-700">{selectedPart.detail}</p>
          <div className="grid gap-2">
            {(Object.keys(PLANE_PARTS) as PartKey[]).map((part) => (
              <button
                key={part}
                type="button"
                onClick={() => {
                  setActivePart(part);
                  setPaused(true);
                }}
                className={`rounded-xl border px-3 py-2 text-left text-sm transition ${
                  activePart === part
                    ? "border-blue-500 bg-blue-50 text-blue-800"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                }`}
              >
                {PLANE_PARTS[part].label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => {
              setPaused(false);
              setActivePart("battery");
            }}
            className="inline-flex items-center gap-2 rounded-full border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
          >
            <RotateCcw size={13} />
            Reset Explorer
          </button>
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
                  prefetch={false}
                  className="inline-flex items-center text-base font-medium text-blue-700 hover:text-blue-600"
                >
                  Open Plane Dashboard <ArrowUpRight className="ml-1 h-4 w-4" />
                </Link>
                <Link
                  href="/mission-game"
                  prefetch={false}
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
