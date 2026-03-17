"use client";

import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Battery, CalendarDays, Gauge } from "lucide-react";

import { Button } from "@/components/ui/button";
import { GlossarySection } from "@/components/ui/glossary-section";
import { ELECTRIC_PLANE_MEDIA } from "@/lib/electric-plane-media";
import { GLOSSARY_FALLBACK } from "@/lib/glossary";

function ElectricPlaneVisual({ compact = false }: { compact?: boolean }) {
  const media = compact ? ELECTRIC_PLANE_MEDIA.campus : ELECTRIC_PLANE_MEDIA.hero;
  const bullets = compact
    ? [
        "Aircraft-level context helps explain why endurance and reserve margins change from one day to the next.",
        "Charging timing and flight cadence directly affect degradation and turnaround readiness.",
        "Operations, maintenance, and student pilots all need the same picture of battery health before dispatch."
      ]
    : [
        "Monitor state of health, recent decline, and replacement outlook at the aircraft level.",
        "Coordinate flight timing with weather, charging windows, and expected wear impact.",
        "Turn battery telemetry into maintenance and operational planning instead of raw data review."
      ];

  return (
    <figure className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-glass">
      <div
        className={`grid gap-0 ${compact ? "lg:grid-cols-[1.18fr_0.82fr]" : "lg:grid-cols-[1.08fr_0.92fr]"}`}
      >
        <div
          className={`${compact ? "p-6" : "p-7 md:p-8"} flex flex-col justify-between bg-gradient-to-br from-white via-slate-50 to-blue-50`}
        >
          <div className="space-y-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              Aircraft Platform
            </p>
            <div>
              <h3 className="font-[var(--font-heading)] text-2xl text-slate-900">
                {compact ? "Operational electric aircraft context" : media.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">
                {compact
                  ? "Aircraft configuration, turnaround rhythm, and daily operating margin all shape how an electric fleet should be scheduled and maintained."
                  : "AeroCell connects battery condition, aircraft utilization, and operating environment so teams can make better dispatch and maintenance decisions."}
              </p>
            </div>
            <div className="grid gap-3">
              {bullets.map((item) => (
                <div
                  key={item}
                  className="rounded-2xl border border-slate-200 bg-white/85 px-4 py-3 text-sm text-slate-700"
                >
                  {item}
                </div>
              ))}
            </div>
          </div>
          <a
            href={media.creditHref}
            target="_blank"
            rel="noreferrer"
            className="mt-5 text-xs text-slate-500 underline-offset-4 hover:text-slate-700 hover:underline"
          >
            Photo source: {media.creditLabel}
          </a>
        </div>
        <div className="relative min-h-[280px] bg-slate-100">
          <Image
            src={media.src}
            alt={media.alt}
            fill
            priority={!compact}
            sizes={compact ? "(max-width: 1024px) 100vw, 50vw" : "(max-width: 1280px) 100vw, 50vw"}
            className={`object-cover ${compact ? "object-[42%_52%]" : "object-[44%_45%]"}`}
          />
          <div className="absolute inset-0 bg-gradient-to-t from-slate-950/10 to-transparent" />
          <div className="absolute bottom-4 left-4 rounded-full bg-white/92 px-3 py-1 text-xs font-medium text-slate-700 shadow-sm">
            {media.subtitle}
          </div>
        </div>
      </div>
    </figure>
  );
}

export function LandingShell() {
  const glossaryItems = GLOSSARY_FALLBACK.filter((item) =>
    ["soh", "rul", "calendar_score", "charge_window"].includes(item.id)
  );

  return (
    <main className="space-y-20 pb-10">
      <section className="fade-up mx-auto max-w-4xl space-y-7 pt-6 text-center md:pt-10">
        <p className="text-sm font-medium uppercase tracking-[0.16em] text-slate-500">
          AeroCell Platform
        </p>
        <h1 className="section-title text-balance text-slate-900">
          Battery Intelligence for Electric Flight, designed for fast decisions.
        </h1>
        <p className="mx-auto max-w-2xl text-balance text-base leading-relaxed text-slate-600">
          Track battery health, predict remaining useful life, and get flight-day
          recommendations.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link href="/planes">
            <Button className="gap-2 transition duration-200 hover:-translate-y-0.5 hover:shadow-lg">
              Open Planes
              <ArrowRight size={16} />
            </Button>
          </Link>
          <Link href="/mission-game">
            <Button className="bg-white text-slate-900 ring-1 ring-slate-300 transition duration-200 hover:-translate-y-0.5 hover:bg-slate-50 hover:shadow-md">
              Open FlightLab
            </Button>
          </Link>
        </div>
      </section>

      <section className="fade-up space-y-6">
        <ElectricPlaneVisual />
        <div className="grid gap-6 md:grid-cols-3">
          <div className="rounded-2xl border border-slate-200/80 bg-white/80 p-4">
            <p className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Gauge size={16} className="text-blue-700" />
              Live SOH + RUL
            </p>
            <p className="mt-1 text-sm text-slate-600">
              Real-time health signals and replacement planning in one place.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200/80 bg-white/80 p-4">
            <p className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900">
              <CalendarDays size={16} className="text-blue-700" />
              Smart Recommendations
            </p>
            <p className="mt-1 text-sm text-slate-600">
              Day-level guidance for better flight and charging behavior.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200/80 bg-white/80 p-4">
            <p className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Battery size={16} className="text-blue-700" />
              Explainable Insights
            </p>
            <p className="mt-1 text-sm text-slate-600">
              Clear definitions and rationale for pilots, operators, and maintenance planning.
            </p>
          </div>
        </div>
      </section>

      <section className="fade-up grid gap-6 xl:grid-cols-[1.12fr_0.88fr]">
        <ElectricPlaneVisual compact />
        <div className="self-start rounded-[28px] border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-emerald-50 p-6 shadow-glass">
          <h2 className="font-[var(--font-heading)] text-2xl text-slate-900">
            Why This Platform Matters
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            Electric aircraft operations depend on more than charge level alone. AeroCell brings
            battery health, forecast wear, daily conditions, and scheduling decisions into one view.
          </p>
          <div className="mt-5 grid gap-3">
            <div className="rounded-xl border border-slate-200 bg-white/90 px-4 py-3 text-sm text-slate-700">
              Review aircraft health trends early enough to act before availability is affected.
            </div>
            <div className="rounded-xl border border-slate-200 bg-white/90 px-4 py-3 text-sm text-slate-700">
              Schedule charging and flight windows with a better view of thermal and weather exposure.
            </div>
            <div className="rounded-xl border border-slate-200 bg-white/90 px-4 py-3 text-sm text-slate-700">
              Support dispatch, maintenance planning, and pilot decision-making from the same data.
            </div>
          </div>
        </div>
      </section>

      <GlossarySection
        title="Core Terms"
        subtitle="Quick definitions used across the platform."
        items={glossaryItems}
      />
    </main>
  );
}
