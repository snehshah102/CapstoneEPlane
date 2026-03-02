"use client";

import { useMemo, useState } from "react";

import { FlightDayScore, ScoreBreakdown } from "@/lib/contracts/schemas";
import { Badge } from "@/components/ui/badge";

type Props = {
  days: FlightDayScore[];
  breakdownByDate: Record<string, ScoreBreakdown>;
};

type CalendarCell = {
  date: string;
  day: number;
  score: number;
  confidenceTier: "high" | "medium" | "low";
  weatherSummary: string;
} | null;

function scoreClass(score: number) {
  if (score >= 75) return "bg-emerald-500/20 border-emerald-400/40";
  if (score >= 55) return "bg-amber-500/20 border-amber-400/40";
  return "bg-rose-500/20 border-rose-400/40";
}

export function RecommendationCalendar({ days, breakdownByDate }: Props) {
  const [selectedDate, setSelectedDate] = useState<string | null>(
    days[0]?.date ?? null
  );

  const cells = useMemo<CalendarCell[]>(() => {
    if (days.length === 0) return [];
    const sorted = [...days].sort((a, b) => a.date.localeCompare(b.date));
    const firstDate = new Date(`${sorted[0].date}T00:00:00Z`);
    const startOffset = firstDate.getUTCDay();
    const leading = Array.from({ length: startOffset }).map(() => null);
    const mapped = sorted.map((day) => ({
      date: day.date,
      day: new Date(`${day.date}T00:00:00Z`).getUTCDate(),
      score: day.score,
      confidenceTier: day.confidenceTier,
      weatherSummary: day.weatherSummary
    }));
    return [...leading, ...mapped];
  }, [days]);

  const selected =
    selectedDate && days.length
      ? days.find((day) => day.date === selectedDate) ?? null
      : null;
  const breakdown = selected ? breakdownByDate[selected.date] : null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-7 gap-2 text-center text-xs text-slate-400">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((name) => (
          <p key={name}>{name}</p>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-2">
        {cells.map((cell, index) =>
          cell ? (
            <button
              key={cell.date}
              type="button"
              onClick={() => setSelectedDate(cell.date)}
              className={`rounded-lg border p-2 text-left transition hover:brightness-110 ${scoreClass(
                cell.score
              )} ${
                selectedDate === cell.date
                  ? "ring-2 ring-cyan-300/80"
                  : "ring-0 ring-transparent"
              }`}
            >
              <p className="text-xs font-semibold text-white">{cell.day}</p>
              <p className="text-[11px] text-slate-200">{cell.score.toFixed(0)}</p>
            </button>
          ) : (
            <div key={`blank-${index}`} />
          )
        )}
      </div>

      {selected ? (
        <div className="rounded-xl border border-slate-600/40 bg-slate-950/30 p-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="font-semibold text-slate-100">Day Details: {selected.date}</p>
            <Badge
              tone={
                selected.confidenceTier === "high"
                  ? "ok"
                  : selected.confidenceTier === "medium"
                    ? "warn"
                    : "risk"
              }
            >
              {selected.confidenceTier}
            </Badge>
          </div>
          <p className="text-sm text-cyan-200">Score {selected.score.toFixed(1)}</p>
          <p className="text-xs text-slate-300">{selected.weatherSummary}</p>
          {breakdown ? (
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <p className="rounded-md border border-slate-600/30 p-2">
                Weather: <span className="font-semibold">{breakdown.weather.toFixed(1)}</span>
              </p>
              <p className="rounded-md border border-slate-600/30 p-2">
                Thermal: <span className="font-semibold">{breakdown.thermal.toFixed(1)}</span>
              </p>
              <p className="rounded-md border border-slate-600/30 p-2">
                Stress: <span className="font-semibold">{breakdown.stress.toFixed(1)}</span>
              </p>
              <p className="rounded-md border border-slate-600/30 p-2">
                Charging: <span className="font-semibold">{breakdown.charging.toFixed(1)}</span>
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
