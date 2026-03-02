"use client";

import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";

type Props = {
  score: number;
  label: "healthy" | "watch" | "critical";
  explanation: string;
};

const labelMap = {
  healthy: {
    title: "Healthy",
    icon: CheckCircle2,
    color: "text-emerald-700"
  },
  watch: {
    title: "Watch",
    icon: AlertTriangle,
    color: "text-amber-700"
  },
  critical: {
    title: "Critical",
    icon: ShieldAlert,
    color: "text-rose-700"
  }
};

export function HealthMeter({ score, label, explanation }: Props) {
  const normalized = Math.max(0, Math.min(100, score));
  const labelInfo = labelMap[label];
  const Icon = labelInfo.icon;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-wide text-muted">Battery Health Meter</p>
        <p className="text-lg font-semibold text-slate-900">{normalized.toFixed(1)}</p>
      </div>
      <div className="h-3 overflow-hidden rounded-full bg-stone-200">
        <div
          className="h-full rounded-full bg-gradient-to-r from-rose-400 via-amber-300 to-emerald-400 transition-all duration-700"
          style={{ width: `${normalized}%` }}
        />
      </div>
      <p className={`inline-flex items-center gap-1 text-sm font-semibold ${labelInfo.color}`}>
        <Icon size={16} />
        {labelInfo.title}
      </p>
      <p className="text-xs text-muted">{explanation}</p>
    </div>
  );
}
