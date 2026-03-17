"use client";

import ReactECharts from "echarts-for-react";
import { useDeferredValue, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { PlaneTakeoff } from "lucide-react";

import {
  evaluateLearnScenario,
  getGlossary,
  getLearnBaseline,
  getPlanes
} from "@/lib/adapters/api-client";
import type { LearnBaseline, LearnEvaluation, PlaneSummary } from "@/lib/contracts/schemas";
import { HealthMeter } from "@/components/ui/health-meter";
import { Card } from "@/components/ui/card";
import { GlossarySection } from "@/components/ui/glossary-section";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { GLOSSARY_FALLBACK } from "@/lib/glossary";

type ControlKey =
  | "ambientTempC"
  | "flightDurationMin"
  | "expectedPowerKw"
  | "windSeverity"
  | "precipitationSeverity"
  | "chargeTargetSoc"
  | "chargeLeadHours"
  | "highSocIdleHours"
  | "flightsPerWeek"
  | "thermalManagementQuality"
  | "cellImbalanceSeverity"
  | "socEstimatorUncertainty";

const controlMeta: Record<ControlKey, { label: string; min: number; max: number; step: number }> = {
  ambientTempC: { label: "Ambient Temperature (C)", min: -10, max: 45, step: 1 },
  flightDurationMin: { label: "Flight Duration (min)", min: 15, max: 120, step: 1 },
  expectedPowerKw: { label: "Expected Power (kW)", min: 15, max: 65, step: 1 },
  windSeverity: { label: "Wind Severity", min: 0, max: 100, step: 1 },
  precipitationSeverity: { label: "Precipitation Severity", min: 0, max: 100, step: 1 },
  chargeTargetSoc: { label: "Charge Target SOC (%)", min: 50, max: 100, step: 1 },
  chargeLeadHours: { label: "Charge Lead Hours", min: 0, max: 48, step: 1 },
  highSocIdleHours: { label: "High SOC Idle Hours", min: 0, max: 36, step: 1 },
  flightsPerWeek: { label: "Flights Per Week", min: 0, max: 14, step: 1 },
  thermalManagementQuality: {
    label: "Thermal Management Quality",
    min: 0,
    max: 100,
    step: 1
  },
  cellImbalanceSeverity: { label: "Cell Imbalance Severity", min: 0, max: 100, step: 1 },
  socEstimatorUncertainty: { label: "SOC Estimator Uncertainty", min: 0, max: 100, step: 1 }
};

type Props = {
  initialPlanes?: PlaneSummary[];
  initialBaseline?: LearnBaseline;
  initialEvaluation?: LearnEvaluation;
};

export function LearnSimulator({
  initialPlanes,
  initialBaseline,
  initialEvaluation
}: Props) {
  const [planeId, setPlaneId] = useState("166");
  const planesQuery = useQuery({
    queryKey: ["planes"],
    queryFn: getPlanes,
    initialData: initialPlanes ? { planes: initialPlanes } : undefined,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false
  });
  const baselineQuery = useQuery({
    queryKey: ["learn-baseline", planeId],
    queryFn: () => getLearnBaseline(planeId),
    initialData: planeId === initialBaseline?.planeId && initialBaseline
      ? { baseline: initialBaseline, evaluation: initialEvaluation }
      : undefined,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false
  });
  const glossaryQuery = useQuery({
    queryKey: ["glossary"],
    queryFn: getGlossary
  });

  const baselineInputs = baselineQuery.data?.baseline.baselineInputs;
  const [inputs, setInputs] = useState<Record<string, number> | null>(null);

  const currentInputs = useMemo(() => {
    if (inputs) return inputs;
    if (!baselineInputs) return null;
    return { ...baselineInputs };
  }, [baselineInputs, inputs]);
  const deferredInputs = useDeferredValue(currentInputs);
  const evaluationQuery = useQuery({
    queryKey: ["learn-evaluate", planeId, deferredInputs],
    queryFn: () => evaluateLearnScenario(planeId, deferredInputs),
    enabled: Boolean(inputs && deferredInputs),
    placeholderData: keepPreviousData
  });
  const resolvedEvaluation = inputs
    ? evaluationQuery.data?.evaluation ?? baselineQuery.data?.evaluation ?? initialEvaluation
    : baselineQuery.data?.evaluation ?? initialEvaluation;
  const computed = resolvedEvaluation?.outputs ?? null;

  const trajectoryOption = useMemo(() => {
    if (!resolvedEvaluation) return null;
    return {
      animation: false,
      tooltip: { trigger: "axis" },
      legend: { data: ["Baseline", "Simulated"], textStyle: { color: "#475569" } },
      xAxis: {
        type: "category",
        data: resolvedEvaluation.trajectory.map((point) => point.label),
        axisLabel: { color: "#64748b" }
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        axisLabel: { color: "#64748b" }
      },
      grid: { left: 36, right: 16, top: 34, bottom: 30 },
      series: [
        {
          name: "Baseline",
          type: "line",
          smooth: true,
          data: resolvedEvaluation.trajectory.map((point) => point.baseline),
          lineStyle: { color: "#94a3b8", width: 2 }
        },
        {
          name: "Simulated",
          type: "line",
          smooth: true,
          data: resolvedEvaluation.trajectory.map((point) => point.simulated),
          lineStyle: { color: "#2563eb", width: 3 },
          areaStyle: { color: "rgba(37,99,235,0.12)" }
        }
      ]
    };
  }, [resolvedEvaluation]);

  if (!planesQuery.data || !baselineQuery.data || !currentInputs || !computed) {
    return (
      <main className="space-y-6">
        <section className="space-y-2">
          <div className="h-10 w-64 animate-pulse rounded-2xl bg-slate-200/80" />
          <div className="h-5 w-[28rem] max-w-full animate-pulse rounded-xl bg-slate-100" />
        </section>

        <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <Card className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="h-7 w-44 animate-pulse rounded-xl bg-slate-200/80" />
              <div className="h-9 w-44 animate-pulse rounded-full bg-slate-100" />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {Array.from({ length: 8 }).map((_, index) => (
                <div key={index} className="rounded-xl border border-stone-200 bg-white/75 p-3">
                  <div className="h-4 w-32 animate-pulse rounded bg-slate-200/80" />
                  <div className="mt-4 h-3 w-full animate-pulse rounded-full bg-slate-100" />
                  <div className="mt-3 h-5 w-10 animate-pulse rounded bg-slate-200/80" />
                </div>
              ))}
            </div>
          </Card>

          <Card className="space-y-4">
            <div className="h-7 w-52 animate-pulse rounded-xl bg-slate-200/80" />
            <div className="h-2.5 w-full animate-pulse rounded-full bg-slate-100" />
            {Array.from({ length: 4 }).map((_, index) => (
              <div
                key={index}
                className="h-12 animate-pulse rounded-xl border border-stone-200 bg-stone-50"
              />
            ))}
            <div className="rounded-2xl border border-blue-100 bg-blue-50/65 p-4">
              <div className="h-4 w-32 animate-pulse rounded bg-blue-100" />
              <div className="mt-3 h-8 w-48 animate-pulse rounded-xl bg-white/80" />
              <div className="mt-4 h-10 animate-pulse rounded-full bg-white/90" />
            </div>
          </Card>
        </section>
      </main>
    );
  }
  if (
    (planesQuery.isError && !planesQuery.data) ||
    (baselineQuery.isError && !baselineQuery.data) ||
    (evaluationQuery.isError && !resolvedEvaluation)
  ) {
    return <div className="text-sm text-rose-600">Learn simulator data unavailable.</div>;
  }

  const glossaryItems = (glossaryQuery.data?.items ?? GLOSSARY_FALLBACK).filter(
    (item) => ["soh", "rul", "risk", "confidence"].includes(item.id)
  );
  const planeProgress = Math.max(8, Math.min(100, (computed.expectedRangeKm / 250) * 100));
  const outputsBusy = evaluationQuery.isFetching;

  return (
    <main className="space-y-6">
      <section>
        <h1 className="section-title text-slate-900">Learn: What Drives SOH?</h1>
        <p className="text-sm text-muted">
          Adjust operations and environment factors to see immediate changes in projected SOH and RUL.
        </p>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="font-semibold text-slate-900">Simulation Inputs</p>
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted">
                Plane{" "}
                <select
                  value={planeId}
                  onChange={(event) => {
                    setPlaneId(event.target.value);
                    setInputs(null);
                  }}
                  className="ml-1 rounded-md border border-stone-300 bg-white px-2 py-1 text-slate-900"
                >
                  {planesQuery.data?.planes.map((plane) => (
                    <option key={plane.planeId} value={plane.planeId}>
                      {plane.planeId}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                onClick={() => setInputs({ ...baselineQuery.data!.baseline.baselineInputs })}
                className="rounded-md border border-stone-300 bg-white px-2 py-1 text-xs text-slate-700"
              >
                Reset to Baseline
              </button>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {(Object.keys(controlMeta) as ControlKey[]).map((key) => {
              const meta = controlMeta[key];
              const value = Number(currentInputs[key]);
              return (
                <div key={key} className="rounded-xl border border-stone-200 bg-white/75 p-3">
                  <label className="text-xs text-muted">{meta.label}</label>
                  <input
                    type="range"
                    min={meta.min}
                    max={meta.max}
                    step={meta.step}
                    value={value}
                    onChange={(event) =>
                      setInputs((prev) => ({
                        ...(prev ?? currentInputs),
                        [key]: Number(event.target.value)
                      }))
                    }
                    className="mt-2 w-full accent-blue-600"
                  />
                  <p className="text-sm font-semibold text-blue-700">{value.toFixed(0)}</p>
                </div>
              );
            })}
          </div>
        </Card>

        <Card className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="font-semibold text-slate-900">Simulation Outputs</p>
            <InfoTooltip
              term="Simulation outputs"
              plainLanguage="These are live model outputs that react to your selected inputs."
              whyItMatters="Students can see which factors move SOH and RUL most."
            />
          </div>
          <p className="text-xs text-slate-500">
            {outputsBusy ? "Refreshing live scenario..." : "Live scenario outputs update from the current plane state."}
          </p>
          <HealthMeter
            score={computed.healthScore}
            label={computed.healthLabel}
            explanation={computed.healthExplanation}
          />
          <div className="grid gap-2 text-sm">
            <p className="rounded-xl border border-stone-200 bg-stone-50 p-2">
              Predicted SOH Delta: <span className="font-semibold">{computed.sohImpactDelta}</span>
            </p>
            <p className="rounded-xl border border-stone-200 bg-stone-50 p-2">
              RUL Shift: <span className="font-semibold">{computed.rulDaysShift} days</span>
            </p>
            <p className="rounded-xl border border-stone-200 bg-stone-50 p-2">
              Recommended action:{" "}
              <span className="font-semibold">{computed.recommendationSummary}</span>
            </p>
          </div>

          <div className="rounded-2xl border border-blue-100 bg-blue-50/65 p-4">
            <p className="text-xs uppercase tracking-wide text-muted">Estimated Mission Reach</p>
            <p className="text-2xl font-semibold text-slate-900">
              {computed.expectedRangeKm} km estimated range
            </p>
            <div className="relative mt-3 h-10 rounded-full bg-white">
              <div className="absolute left-3 top-1/2 h-[2px] w-[calc(100%-24px)] -translate-y-1/2 bg-stone-200" />
              <PlaneTakeoff
                className="absolute top-1/2 -translate-y-1/2 text-blue-700 transition-all duration-500"
                size={18}
                style={{ left: `calc(${planeProgress}% - 9px)` }}
              />
            </div>
          </div>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <Card>
          <p className="mb-2 font-[var(--font-heading)] text-xl text-slate-900">
            SOH Projection Trajectory
          </p>
          {trajectoryOption ? (
            <ReactECharts option={trajectoryOption} style={{ height: 260, width: "100%" }} />
          ) : null}
        </Card>
        <Card>
          <details className="rounded-xl border border-stone-200 bg-white/80 p-3 text-sm">
            <summary className="cursor-pointer font-semibold text-slate-900">
              Show model assumptions
            </summary>
            <p className="mt-2 text-xs text-muted">
              Learn outputs are now anchored to live plane health, current forecast confidence,
              and model-backed SOH trajectory data for the selected aircraft.
            </p>
          </details>
        </Card>
      </section>

      <GlossarySection
        title="Learn Page Glossary"
        subtitle="Definitions for simulation terms."
        items={glossaryItems}
      />
    </main>
  );
}
