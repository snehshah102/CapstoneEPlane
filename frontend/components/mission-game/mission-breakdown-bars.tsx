"use client";

import { MissionGameResult } from "@/lib/contracts/schemas";

type Props = {
  breakdown: MissionGameResult["breakdown"];
};

function meterColor(value: number) {
  if (value >= 78) return "bg-emerald-500";
  if (value >= 60) return "bg-amber-500";
  return "bg-rose-500";
}

export function MissionBreakdownBars({ breakdown }: Props) {
  const items = [
    { label: "Battery Impact", value: breakdown.batteryImpact },
    { label: "Safety Confidence", value: breakdown.safetyConfidence },
    { label: "Cost Efficiency", value: breakdown.costEfficiency }
  ];

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.label}>
          <div className="mb-1 flex items-center justify-between text-sm">
            <p className="text-slate-700">{item.label}</p>
            <p className="font-medium text-slate-900">{item.value.toFixed(1)}</p>
          </div>
          <div className="h-2 rounded-full bg-slate-200">
            <div
              className={`h-full rounded-full ${meterColor(item.value)}`}
              style={{ width: `${Math.max(0, Math.min(100, item.value))}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
