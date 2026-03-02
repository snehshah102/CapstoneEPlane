"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getLearnBaseline, getPlanes } from "@/lib/adapters/api-client";
import { HealthMeter } from "@/components/ui/health-meter";
import { Card } from "@/components/ui/card";

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

const controlMeta: Record<
  ControlKey,
  { label: string; min: number; max: number; step: number }
> = {
  ambientTempC: { label: "Ambient Temperature (C)", min: -10, max: 45, step: 1 },
  flightDurationMin: { label: "Flight Duration (min)", min: 15, max: 120, step: 1 },
  expectedPowerKw: { label: "Expected Power (kW)", min: 15, max: 65, step: 1 },
  windSeverity: { label: "Wind Severity", min: 0, max: 100, step: 1 },
  precipitationSeverity: { label: "Precipitation Severity", min: 0, max: 100, step: 1 },
  chargeTargetSoc: { label: "Charge Target SOC (%)", min: 50, max: 100, step: 1 },
  chargeLeadHours: { label: "Charge Lead Hours", min: 0, max: 48, step: 1 },
  highSocIdleHours: { label: "High SOC Idle Hours", min: 0, max: 36, step: 1 },
  flightsPerWeek: { label: "Flights Per Week", min: 0, max: 14, step: 1 },
  thermalManagementQuality: { label: "Thermal Management Quality", min: 0, max: 100, step: 1 },
  cellImbalanceSeverity: { label: "Cell Imbalance Severity", min: 0, max: 100, step: 1 },
  socEstimatorUncertainty: { label: "SOC Estimator Uncertainty", min: 0, max: 100, step: 1 }
};

function healthLabel(score: number): "healthy" | "watch" | "critical" {
  if (score >= 75) return "healthy";
  if (score >= 55) return "watch";
  return "critical";
}

function labelExplanation(label: "healthy" | "watch" | "critical") {
  if (label === "healthy") {
    return "Low projected stress profile under current settings.";
  }
  if (label === "watch") {
    return "Moderate stress profile. Consider reducing high-SOC dwell and weather exposure.";
  }
  return "High stress profile. Shift operation plan and charging strategy.";
}

export function LearnSimulator() {
  const [planeId, setPlaneId] = useState("166");
  const planesQuery = useQuery({ queryKey: ["planes"], queryFn: getPlanes });
  const baselineQuery = useQuery({
    queryKey: ["learn-baseline", planeId],
    queryFn: () => getLearnBaseline(planeId)
  });

  const baselineInputs = baselineQuery.data?.baseline.baselineInputs;
  const baselineOutputs = baselineQuery.data?.baseline.baselineOutputs;
  const [inputs, setInputs] = useState<Record<string, number> | null>(null);

  const currentInputs = useMemo(() => {
    if (inputs) return inputs;
    if (!baselineInputs) return null;
    return { ...baselineInputs };
  }, [baselineInputs, inputs]);

  const computed = useMemo(() => {
    if (!currentInputs || !baselineOutputs || !baselineInputs) return null;

    const tempPenalty = Math.abs(currentInputs.ambientTempC - 21) * 0.12;
    const durationPenalty = (currentInputs.flightDurationMin - 45) * 0.045;
    const powerPenalty = (currentInputs.expectedPowerKw - 28) * 0.06;
    const weatherPenalty =
      currentInputs.windSeverity * 0.014 +
      currentInputs.precipitationSeverity * 0.01;
    const chargingPenalty =
      Math.max(0, currentInputs.chargeTargetSoc - 80) * 0.025 +
      currentInputs.chargeLeadHours * 0.012 +
      currentInputs.highSocIdleHours * 0.02;
    const operationsPenalty = currentInputs.flightsPerWeek * 0.03;
    const systemPenalty =
      (100 - currentInputs.thermalManagementQuality) * 0.012 +
      currentInputs.cellImbalanceSeverity * 0.01 +
      currentInputs.socEstimatorUncertainty * 0.008;

    const totalPenalty =
      tempPenalty +
      durationPenalty +
      powerPenalty +
      weatherPenalty +
      chargingPenalty +
      operationsPenalty +
      systemPenalty;

    const sohImpactDelta = Number((-0.05 - totalPenalty * 0.2).toFixed(2));
    const score = Number(
      Math.max(0, Math.min(100, baselineOutputs.healthScore - totalPenalty)).toFixed(2)
    );
    const label = healthLabel(score);
    const rulShift = Number((-totalPenalty * 6).toFixed(1));

    return {
      sohImpactDelta,
      healthScore: score,
      healthLabel: label,
      healthExplanation: labelExplanation(label),
      rulDaysShift: rulShift,
      recommendationSummary:
        label === "healthy"
          ? "Profile is battery-friendly. Keep this operation plan."
          : label === "watch"
            ? "Profile is acceptable but could improve with lower SOC target and shorter lead time."
            : "Profile is high stress. Reduce charge target and avoid long high-SOC idle windows."
    };
  }, [baselineInputs, baselineOutputs, currentInputs]);

  if (planesQuery.isLoading || baselineQuery.isLoading || !currentInputs || !computed) {
    return <div className="text-sm text-slate-300">Loading learn simulator...</div>;
  }
  if (planesQuery.isError || baselineQuery.isError || !baselineQuery.data) {
    return <div className="text-sm text-rose-300">Learn simulator data unavailable.</div>;
  }

  return (
    <main className="space-y-6">
      <section>
        <h1 className="font-[var(--font-heading)] text-3xl">Learn: What drives SOH?</h1>
        <p className="text-sm text-slate-300">
          Toggle factors and see how projected battery wear and health state change in real time.
        </p>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="font-semibold text-slate-100">Simulation Inputs</p>
            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-300">
                Plane{" "}
                <select
                  value={planeId}
                  onChange={(event) => {
                    setPlaneId(event.target.value);
                    setInputs(null);
                  }}
                  className="ml-1 rounded-md border border-slate-600/40 bg-slate-950/40 px-2 py-1"
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
                className="rounded-md border border-slate-500/40 px-2 py-1 text-xs text-slate-200"
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
                <div key={key} className="rounded-lg border border-slate-600/35 p-3">
                  <label className="text-xs text-slate-300">{meta.label}</label>
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
                    className="mt-2 w-full"
                  />
                  <p className="text-sm font-semibold text-cyan-200">{value.toFixed(0)}</p>
                </div>
              );
            })}
          </div>
        </Card>

        <Card className="space-y-4">
          <p className="font-semibold text-slate-100">Simulation Outputs</p>
          <HealthMeter
            score={computed.healthScore}
            label={computed.healthLabel}
            explanation={computed.healthExplanation}
          />
          <div className="grid gap-2 text-sm">
            <p className="rounded-lg border border-slate-600/35 p-2">
              Predicted SOH Impact Delta:{" "}
              <span className="font-semibold">{computed.sohImpactDelta}</span>
            </p>
            <p className="rounded-lg border border-slate-600/35 p-2">
              RUL Shift (days): <span className="font-semibold">{computed.rulDaysShift}</span>
            </p>
            <p className="rounded-lg border border-slate-600/35 p-2">
              Recommendation:{" "}
              <span className="font-semibold">{computed.recommendationSummary}</span>
            </p>
          </div>
          <details className="rounded-lg border border-slate-600/35 p-3 text-sm">
            <summary className="cursor-pointer font-semibold text-slate-100">
              Show model assumptions
            </summary>
            <p className="mt-2 text-xs text-slate-300">
              This simulator uses transparent mock weighting to demonstrate how
              operations, weather, and charging behavior can influence projected SOH and RUL.
              It is intentionally educational and model-ready for future backend replacement.
            </p>
          </details>
        </Card>
      </section>
    </main>
  );
}
