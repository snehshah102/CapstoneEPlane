"use client";

import { MissionGameResult } from "@/lib/contracts/schemas";
import { Badge } from "@/components/ui/badge";
import { MissionBreakdownBars } from "@/components/mission-game/mission-breakdown-bars";

type Props = {
  result: MissionGameResult;
};

function statusCopy(status: MissionGameResult["status"]) {
  if (status === "recommended") {
    return "Flight plan is strong for current operating conditions.";
  }
  if (status === "caution") {
    return "Flight is feasible, but adjustments are recommended.";
  }
  return "Flight plan is high-risk under current inputs.";
}

export function MissionScorePanel({ result }: Props) {
  const statusTone =
    result.status === "recommended"
      ? "ok"
      : result.status === "caution"
        ? "warn"
        : "risk";

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[0.36fr_0.64fr]">
        <div className="flex flex-col items-center rounded-2xl border border-slate-200 bg-white p-4">
          <div
            className="relative flex h-36 w-36 items-center justify-center rounded-full"
            style={{
              background: `conic-gradient(#2563eb ${result.overallScore * 3.6}deg, #e2e8f0 0deg)`
            }}
          >
            <div className="flex h-[116px] w-[116px] flex-col items-center justify-center rounded-full bg-white">
              <p className="text-3xl font-semibold text-slate-900">
                {result.overallScore.toFixed(1)}
              </p>
              <p className="text-xs text-slate-500">Composite</p>
            </div>
          </div>
          <Badge tone={statusTone} className="mt-3 capitalize">
            {result.status.replace("_", " ")}
          </Badge>
        </div>

        <div className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
          <p className="text-sm text-slate-700">{statusCopy(result.status)}</p>
          <MissionBreakdownBars breakdown={result.breakdown} />
          <div className="grid gap-2 md:grid-cols-2">
            <p className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700">
              Estimated Cost: <span className="font-semibold">${result.estimatedCostUsd.toFixed(2)}</span>
            </p>
            <p className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700">
              Battery Impact:{" "}
              <span className="font-semibold">{result.estimatedBatteryImpact.toFixed(1)} pts</span>
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="mb-2 text-sm font-semibold text-slate-900">Why this score</p>
          <ul className="space-y-1 text-sm text-slate-700">
            {result.why.map((item) => (
              <li key={item}>- {item}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="mb-2 text-sm font-semibold text-slate-900">Suggested adjustments</p>
          <ul className="space-y-1 text-sm text-slate-700">
            {result.suggestions.map((item) => (
              <li key={item.action}>
                - {item.action}{" "}
                <span className="text-blue-700">(+{item.expectedScoreDelta.toFixed(1)})</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
