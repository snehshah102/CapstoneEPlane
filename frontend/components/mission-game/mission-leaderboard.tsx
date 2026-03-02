"use client";

import { useMemo, useState } from "react";

import { MissionGameResult } from "@/lib/contracts/schemas";
import { Badge } from "@/components/ui/badge";
import { MissionBreakdownBars } from "@/components/mission-game/mission-breakdown-bars";
import { MissionGameInput } from "@/lib/contracts/schemas";

export type LeaderboardEntry = {
  id: string;
  missionName: string;
  mode: "single" | "fleet_compare";
  planeLabel: string;
  score: number;
  status: MissionGameResult["status"];
  timestamp: string;
  input: MissionGameInput;
  result: MissionGameResult;
};

type Props = {
  entries: LeaderboardEntry[];
  onClear: () => void;
};

export function MissionLeaderboard({ entries, onClear }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedEntry = useMemo(
    () => entries.find((entry) => entry.id === selectedId) ?? null,
    [entries, selectedId]
  );

  return (
    <div className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-[var(--font-heading)] text-lg text-slate-900">Session Leaderboard</h3>
        <button
          type="button"
          onClick={onClear}
          className="rounded-full border border-slate-300 px-3 py-1 text-xs text-slate-700 hover:bg-slate-50"
        >
          Clear
        </button>
      </div>
      {entries.length === 0 ? (
        <p className="text-sm text-slate-600">No saved runs yet.</p>
      ) : (
        <div className="space-y-2">
          {entries.map((entry, index) => (
            <button
              key={entry.id}
              type="button"
              onClick={() =>
                setSelectedId((prev) => (prev === entry.id ? null : entry.id))
              }
              className={`w-full cursor-pointer rounded-xl border px-3 py-2 text-left text-sm transition ${
                selectedId === entry.id
                  ? "border-blue-500 bg-blue-50 ring-2 ring-blue-200"
                  : "border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/50"
              }`}
            >
              <div className="mb-1 flex items-center justify-between">
                <p className="font-medium text-slate-900">{entry.missionName}</p>
                <p className="font-semibold text-blue-700">{entry.score.toFixed(1)}</p>
              </div>
              <div className="flex items-center justify-between text-xs text-slate-600">
                <span>{entry.planeLabel}</span>
                <span>{new Date(entry.timestamp).toLocaleTimeString()}</span>
              </div>
              <div className="mt-1">
                <Badge
                  tone={
                    entry.status === "recommended"
                      ? "ok"
                      : entry.status === "caution"
                        ? "warn"
                        : "risk"
                  }
                  className="capitalize"
                >
                  {entry.status.replace("_", " ")}
                </Badge>
              </div>
            </button>
          ))}
        </div>
      )}
      {selectedEntry ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="mb-2 text-xs uppercase tracking-wide text-slate-500">Session Detail</p>
          <p className="text-sm text-slate-700">
            {selectedEntry.mode === "single" ? "Detailed mode" : "Fleet compare"} |{" "}
            {selectedEntry.planeLabel}
          </p>
          <p className="mt-1 text-xs text-slate-600">
            Duration {selectedEntry.input.plannedDurationMin} min | Distance{" "}
            {selectedEntry.input.routeDistanceKm} km | Target SOC {selectedEntry.input.targetSoc}%
          </p>
          <div className="mt-3">
            <MissionBreakdownBars breakdown={selectedEntry.result.breakdown} />
          </div>
          <ul className="mt-2 space-y-1 text-xs text-slate-700">
            {selectedEntry.result.why.slice(0, 3).map((whyLine) => (
              <li key={whyLine}>- {whyLine}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
