"use client";

import { MissionGamePlaneResult } from "@/lib/contracts/schemas";
import { Badge } from "@/components/ui/badge";

type Props = {
  rows: MissionGamePlaneResult[];
};

export function MissionCompareTable({ rows }: Props) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="px-3 py-2">Plane</th>
            <th className="px-3 py-2">Score</th>
            <th className="px-3 py-2">Battery</th>
            <th className="px-3 py-2">Confidence</th>
            <th className="px-3 py-2">Cost</th>
            <th className="px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={row.planeId}
              className={index === 0 ? "bg-blue-50/50" : "border-t border-slate-100"}
            >
              <td className="px-3 py-2 text-slate-800">
                {row.registration} ({row.planeId})
              </td>
              <td className="px-3 py-2 font-semibold text-slate-900">
                {row.overallScore.toFixed(1)}
              </td>
              <td className="px-3 py-2">{row.breakdown.batteryImpact.toFixed(1)}</td>
              <td className="px-3 py-2">{row.breakdown.safetyConfidence.toFixed(1)}</td>
              <td className="px-3 py-2">${row.estimatedCostUsd.toFixed(2)}</td>
              <td className="px-3 py-2">
                <Badge
                  tone={
                    row.status === "recommended"
                      ? "ok"
                      : row.status === "caution"
                        ? "warn"
                        : "risk"
                  }
                  className="capitalize"
                >
                  {row.status.replace("_", " ")}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
