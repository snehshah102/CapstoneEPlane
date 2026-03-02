"use client";

import Link from "next/link";
import { ArrowRight, Battery, CalendarDays, Gauge } from "lucide-react";

import { Button } from "@/components/ui/button";
import { GlossarySection } from "@/components/ui/glossary-section";
import { GLOSSARY_FALLBACK } from "@/lib/glossary";

function ElectricPlaneVisual({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`overflow-hidden rounded-[28px] border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-blue-50 shadow-glass ${compact ? "p-4" : "p-6"}`}
    >
      <svg viewBox="0 0 760 380" className={`${compact ? "h-52" : "h-[340px]"} w-full`}>
        <defs>
          <linearGradient id="hull" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#f8fbff" />
            <stop offset="100%" stopColor="#d7e5ff" />
          </linearGradient>
          <linearGradient id="wing" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#6ea8ff" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#2563eb" stopOpacity="0.8" />
          </linearGradient>
          <linearGradient id="engine" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#1d4ed8" />
            <stop offset="100%" stopColor="#0ea5e9" />
          </linearGradient>
        </defs>
        <ellipse cx="378" cy="320" rx="262" ry="26" fill="#b8c5db" opacity="0.32" />
        <path d="M120 224 L310 186 L567 175 L654 195 L573 212 L312 220 Z" fill="url(#wing)" />
        <path
          d="M162 206 C188 146, 295 116, 438 124 C520 128, 586 149, 627 184 C638 193, 638 208, 627 217 C584 248, 518 269, 434 274 C291 282, 188 248, 162 206Z"
          fill="url(#hull)"
        />
        <circle cx="452" cy="201" r="31" fill="#173c78" />
        <circle cx="452" cy="201" r="21" fill="url(#engine)" />
        <circle cx="452" cy="201" r="9" fill="#cffafe" opacity="0.88" />
        <path d="M245 182 L182 122 L257 165 Z" fill="#a6b3ca" />
        <path d="M253 240 L178 295 L286 250 Z" fill="#98a9c5" />
        <path d="M563 176 L634 133 L594 186 Z" fill="#dbe8ff" />
        <path d="M562 222 L636 251 L593 214 Z" fill="#c7dcff" />
        <rect x="145" y="232" width="92" height="9" rx="4.5" fill="#1e40af" opacity="0.26" />
      </svg>
    </div>
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
          recommendations with a smooth, student-friendly interface.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link href="/planes" prefetch={false}>
            <Button className="gap-2">
              Open Planes
              <ArrowRight size={16} />
            </Button>
          </Link>
          <Link href="/planes" prefetch={false}>
            <Button className="bg-white text-slate-900 ring-1 ring-slate-300 hover:bg-slate-50">
              Open Dashboards
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
              Clear definitions and rationale made for student presentations.
            </p>
          </div>
        </div>
      </section>

      <section className="fade-up grid gap-6 md:grid-cols-2">
        <ElectricPlaneVisual compact />
        <div className="rounded-[28px] border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-emerald-50 p-6 shadow-glass">
          <h2 className="font-[var(--font-heading)] text-2xl text-slate-900">
            Why This Platform Matters
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            Electric aircraft viability depends on battery reliability, efficient operations,
            and confident maintenance planning. AeroCell brings those decisions into one view.
          </p>
          <div className="mt-5 grid gap-3">
            <div className="rounded-xl border border-slate-200 bg-white/90 px-4 py-3 text-sm text-slate-700">
              Track health trends over time to identify wear early.
            </div>
            <div className="rounded-xl border border-slate-200 bg-white/90 px-4 py-3 text-sm text-slate-700">
              Plan charging windows and flight days to reduce avoidable stress.
            </div>
            <div className="rounded-xl border border-slate-200 bg-white/90 px-4 py-3 text-sm text-slate-700">
              Translate telemetry into clear actions students and pilots can use.
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
