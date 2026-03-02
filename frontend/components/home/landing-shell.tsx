"use client";

import Link from "next/link";
import { ArrowRight, BatteryCharging, CalendarDays, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export function LandingShell() {
  return (
    <main className="space-y-10">
      <section className="glass relative overflow-hidden rounded-3xl px-6 py-10 md:px-10 md:py-14">
        <div className="absolute -left-20 -top-20 h-64 w-64 rounded-full bg-cyan-400/20 blur-3xl" />
        <div className="absolute -bottom-20 right-0 h-64 w-64 rounded-full bg-emerald-500/20 blur-3xl" />
        <div className="relative grid items-center gap-8 lg:grid-cols-2">
          <div className="space-y-5">
            <p className="inline-flex items-center gap-2 rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-xs text-cyan-200">
              <Sparkles size={14} />
              Student Experience Demo
            </p>
            <h1 className="font-[var(--font-heading)] text-4xl leading-tight md:text-6xl">
              AeroCell makes battery intelligence visible.
            </h1>
            <p className="max-w-xl text-sm text-slate-300 md:text-base">
              Understand battery health, discover the best days to fly, and learn
              what factors drive SOH through an interactive experience designed
              for presentation day.
            </p>
            <div className="flex flex-wrap gap-3">
              <Link href="/experience">
                <Button className="gap-2">
                  Start the Experience
                  <ArrowRight size={16} />
                </Button>
              </Link>
              <Link href="/learn">
                <Button className="bg-slate-100 text-slate-900 hover:bg-white">
                  Open Learn Simulator
                </Button>
              </Link>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-600/40 bg-slate-950/30 p-4">
            <svg
              viewBox="0 0 720 380"
              className="h-[260px] w-full animate-rise-in"
              role="img"
              aria-label="Stylized electric plane illustration"
            >
              <defs>
                <linearGradient id="planeBody" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#dbeafe" />
                  <stop offset="100%" stopColor="#7dd3fc" />
                </linearGradient>
                <linearGradient id="wingGlow" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.2" />
                  <stop offset="100%" stopColor="#10b981" stopOpacity="0.75" />
                </linearGradient>
              </defs>
              <rect x="0" y="0" width="720" height="380" fill="transparent" />
              <ellipse cx="350" cy="300" rx="260" ry="30" fill="#0f172a" opacity="0.35" />
              <path
                d="M120 220 L300 190 L560 180 L640 195 L560 210 L300 220 Z"
                fill="url(#wingGlow)"
              />
              <path
                d="M160 210 C180 150, 280 120, 430 130 C500 135, 570 155, 610 185 C620 193, 620 206, 610 214 C570 244, 500 266, 430 271 C280 280, 180 252, 160 210Z"
                fill="url(#planeBody)"
              />
              <circle cx="445" cy="200" r="26" fill="#0f172a" opacity="0.92" />
              <circle cx="445" cy="200" r="17" fill="#22d3ee" opacity="0.75" />
              <path d="M230 185 L180 130 L250 165 Z" fill="#9ca3af" />
              <path d="M248 238 L185 285 L274 250 Z" fill="#94a3b8" />
              <path d="M560 177 L625 138 L585 183 Z" fill="#bae6fd" />
              <path d="M560 224 L626 251 L586 218 Z" fill="#a5f3fc" />
            </svg>
            <p className="mt-3 text-xs text-slate-300">
              Powered by flight telemetry + weather-informed optimization (mock
              today, model-ready tomorrow).
            </p>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <Card className="space-y-3">
          <BatteryCharging className="h-5 w-5 text-cyan-300" />
          <h2 className="font-[var(--font-heading)] text-xl">Why SOH matters</h2>
          <p className="text-sm text-slate-300">
            SOH shows how close a battery is to new condition. Lower SOH means
            less endurance and faster wear progression.
          </p>
        </Card>
        <Card className="space-y-3">
          <CalendarDays className="h-5 w-5 text-emerald-300" />
          <h2 className="font-[var(--font-heading)] text-xl">What we predict</h2>
          <p className="text-sm text-slate-300">
            We forecast replacement timing, remaining useful life, and
            day-by-day flight suitability to reduce unnecessary battery stress.
          </p>
        </Card>
        <Card className="space-y-3">
          <Sparkles className="h-5 w-5 text-amber-300" />
          <h2 className="font-[var(--font-heading)] text-xl">How to explore</h2>
          <p className="text-sm text-slate-300">
            Use the Experience page for guided insights, Planes for detailed
            dashboards, and Learn to interactively test SOH factors.
          </p>
        </Card>
      </section>
    </main>
  );
}
