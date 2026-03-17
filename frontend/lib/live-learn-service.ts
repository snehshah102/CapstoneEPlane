import {
  type LearnBaseline,
  type LearnEvaluation,
  type LearnInputs,
  LearnBaselineResponseSchema,
  LearnEvaluateResponseSchema
} from "@/lib/contracts/schemas";
import { getLivePlanePayload } from "@/lib/live-plane-service";
import { getLivePredictionPayload } from "@/lib/live-prediction-service";

const BASELINE_CACHE_TTL_MS = 5 * 60_000;

type BaselinePayload = { baseline: LearnBaseline; evaluation: LearnEvaluation };
type BaselineCacheEntry = {
  expiresAt: number;
  value?: BaselinePayload;
  promise?: Promise<BaselinePayload>;
};

const baselineCache = new Map<string, BaselineCacheEntry>();

function clamp(value: number, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function round(value: number, digits = 1) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function healthLabel(score: number): "healthy" | "watch" | "critical" {
  if (score >= 75) return "healthy";
  if (score >= 55) return "watch";
  return "critical";
}

function healthExplanation(label: "healthy" | "watch" | "critical", topDrivers: string[]) {
  if (label === "healthy") {
    return "Current operating choices stay inside a battery-friendly envelope.";
  }
  if (label === "watch") {
    const driverText = topDrivers.slice(0, 2).join(" and ").toLowerCase();
    return driverText
      ? `Moderate stress profile. ${driverText} are the main contributors right now.`
      : "Moderate stress profile. Review charging and mission settings before dispatch.";
  }
  const driverText = topDrivers.slice(0, 2).join(" and ").toLowerCase();
  return driverText
    ? `High stress profile. ${driverText} are pushing the scenario beyond the preferred operating window.`
    : "High stress profile. Shift the mission and charging plan to reduce projected wear.";
}

function recommendationSummary(label: "healthy" | "watch" | "critical", topDrivers: string[]) {
  if (!topDrivers.length) {
    return label === "healthy"
      ? "Profile is battery-friendly. Maintain the current operating plan."
      : "Review the operating plan to reduce battery stress.";
  }

  const [first, second] = topDrivers;
  const pair = second ? `${first.toLowerCase()} and ${second.toLowerCase()}` : first.toLowerCase();

  if (label === "healthy") {
    return `Current plan looks healthy. Keep ${pair} inside the current range.`;
  }
  if (label === "watch") {
    return `Most of the projected stress comes from ${pair}. Reduce those first to recover margin.`;
  }
  return `Recommended action: reduce ${pair} before running this mission profile.`;
}

function topDriversFromPenalties(
  penalties: Array<{ label: string; penalty: number }>
) {
  return penalties
    .filter((item) => item.penalty > 1.2)
    .sort((a, b) => b.penalty - a.penalty)
    .slice(0, 3)
    .map((item) => item.label);
}

function sampleTrajectory(
  forecastCurve: Array<{ date: string; soh: number }>,
  scenarioPenalty: number
) {
  const labels = Array.from({ length: 12 }, (_, index) => `W${index + 1}`);
  const baselineCurve = forecastCurve.length
    ? forecastCurve
    : labels.map((_, index) => ({
        date: `W${index + 1}`,
        soh: 100 - index * 0.8
      }));

  return labels.map((label, index) => {
    const curveIndex = Math.min(
      baselineCurve.length - 1,
      Math.floor((index / Math.max(labels.length - 1, 1)) * (baselineCurve.length - 1))
    );
    const baseline = baselineCurve[curveIndex]?.soh ?? 100;
    const simulated = clamp(
      baseline - scenarioPenalty * (0.35 + index * 0.08),
      0,
      100
    );
    return {
      label,
      baseline: round(baseline, 1),
      simulated: round(simulated, 1)
    };
  });
}

async function deriveBaselineInputs(planeId: string): Promise<LearnInputs> {
  const [live, prediction] = await Promise.all([
    getLivePlanePayload(planeId),
    getLivePredictionPayload(planeId)
  ]);

  const health = live.health as {
    currentChargeSoc: number;
    timeSinceLastFlightHours: number;
    healthScore: number;
    pack: {
      voltage: number;
      current: number;
      tempAvg: number;
    };
    lastFlight: {
      durationMin: number | null;
      departureAirport: string | null;
    };
  };
  const ops = (live.ops ?? {}) as {
    flightsPerDayRecent?: number;
  };
  const baselinePowerKw = Math.max(
    18,
    Math.min(65, (Math.abs(health.pack.current) * health.pack.voltage) / 1000)
  );
  const bestMissionDuration = round(
    clamp(Math.min(45, health.lastFlight.durationMin ?? 45), 15, 120),
    0
  );
  const bestExpectedPower = round(clamp(Math.min(28, baselinePowerKw), 15, 65), 0);
  const bestFlightsPerWeek = round(
    clamp(Math.min(Math.max((ops.flightsPerDayRecent ?? 0.9) * 7, 3), 7), 0, 14),
    0
  );
  const bestChargeTarget = round(
    clamp(Math.max(78, Math.min(82, health.currentChargeSoc + 4)), 50, 82),
    0
  );

  return {
    ambientTempC: 21,
    flightDurationMin: bestMissionDuration,
    expectedPowerKw: bestExpectedPower,
    windSeverity: 0,
    precipitationSeverity: 0,
    chargeTargetSoc: bestChargeTarget,
    chargeLeadHours: 0,
    highSocIdleHours: 0,
    flightsPerWeek: bestFlightsPerWeek,
    thermalManagementQuality: 100,
    cellImbalanceSeverity: 0,
    socEstimatorUncertainty: 0
  };
}

export async function evaluateLearnScenario(
  planeId: string,
  inputs: LearnInputs
): Promise<{ evaluation: LearnEvaluation }> {
  const [live, predictionPayload] = await Promise.all([
    getLivePlanePayload(planeId),
    getLivePredictionPayload(planeId)
  ]);

  const health = live.health as {
    sohCurrent: number;
    sohTrend30: number;
    healthScore: number;
    confidence: number;
    pack: {
      tempAvg: number;
    };
  };
  const prediction = predictionPayload.prediction;
  const baselineDuration = Math.max(
    35,
    Math.min(
      90,
      ((live.health as { lastFlight: { durationMin: number | null } }).lastFlight.durationMin ?? 55)
    )
  );
  const baselineFlightsPerWeek = clamp(((live.ops as { flightsPerDayRecent?: number } | undefined)?.flightsPerDayRecent ?? 0.9) * 7, 1, 14);
  const baselinePowerKw = clamp(28 + Math.max(0, 88 - health.sohCurrent) * 0.12, 18, 45);

  const penalties = [
    {
      label: "Temperature control",
      penalty:
        Math.abs(inputs.ambientTempC - 21) * 0.22 +
        Math.max(0, 5 - inputs.ambientTempC) * 0.35 +
        Math.max(0, inputs.ambientTempC - 33) * 0.38
    },
    {
      label: "Mission duration",
      penalty:
        Math.max(0, inputs.flightDurationMin - baselineDuration) * 0.11 +
        Math.max(0, inputs.flightDurationMin - 90) * 0.18
    },
    {
      label: "Power demand",
      penalty:
        Math.max(0, inputs.expectedPowerKw - baselinePowerKw) * 0.28
    },
    {
      label: "Weather exposure",
      penalty:
        inputs.windSeverity * 0.065 + inputs.precipitationSeverity * 0.048
    },
    {
      label: "Charge strategy",
      penalty:
        Math.max(0, inputs.chargeTargetSoc - 82) * 0.42 +
        inputs.chargeLeadHours * 0.21 +
        inputs.highSocIdleHours * 0.27
    },
    {
      label: "Flight cadence",
      penalty:
        Math.max(0, inputs.flightsPerWeek - baselineFlightsPerWeek) * 0.95
    },
    {
      label: "Thermal management",
      penalty: (100 - inputs.thermalManagementQuality) * 0.085
    },
    {
      label: "Cell balance",
      penalty: inputs.cellImbalanceSeverity * 0.07
    },
    {
      label: "SOC estimation",
      penalty: inputs.socEstimatorUncertainty * 0.055
    }
  ];

  const totalPenalty = penalties.reduce((sum, item) => sum + item.penalty, 0);
  const score = round(clamp(health.healthScore - totalPenalty), 2);
  const label = healthLabel(score);
  const topDrivers = topDriversFromPenalties(penalties);
  const dailyWearBase = Math.max(0.02, Math.abs(health.sohTrend30) / 30);
  const sohImpactDelta = round(-(dailyWearBase + totalPenalty * 0.085), 2);
  const rulDaysShift = round(
    -(
      totalPenalty * 2.9 +
      Math.max(0, inputs.chargeTargetSoc - 84) * 0.8 +
      Math.max(0, inputs.flightDurationMin - baselineDuration) * 0.3
    ),
    1
  );
  const expectedRangeKm = round(
    Math.max(
      55,
      2.5 *
        health.sohCurrent *
        (inputs.chargeTargetSoc / 100) *
        (1 - inputs.windSeverity / 240) *
        (1 - Math.max(0, inputs.expectedPowerKw - 28) / 140)
    ),
    1
  );
  const confidence = round(
    clamp(
      prediction.forecast.confidence * 100 -
        inputs.socEstimatorUncertainty * 0.18 -
        inputs.cellImbalanceSeverity * 0.08,
      35,
      95
    ),
    1
  );
  const scenarioPenalty = totalPenalty / 7.5;

  return LearnEvaluateResponseSchema.parse({
    evaluation: {
      planeId,
      outputs: {
        sohImpactDelta,
        healthScore: score,
        healthLabel: label,
        rulDaysShift,
        recommendationSummary: recommendationSummary(label, topDrivers),
        healthExplanation: healthExplanation(label, topDrivers),
        expectedRangeKm,
        confidence,
        topDrivers
      },
      trajectory: sampleTrajectory(prediction.forecastCurve, scenarioPenalty)
    }
  });
}

async function computeLearnBaselinePayload(planeId: string): Promise<BaselinePayload> {
  const baselineInputs = await deriveBaselineInputs(planeId);
  const evaluation = (await evaluateLearnScenario(planeId, baselineInputs)).evaluation;

  const payload = LearnBaselineResponseSchema.parse({
    baseline: {
      planeId,
      assumptionsVersion: "learn_live_v2",
      baselineInputs,
      baselineOutputs: {
        sohImpactDelta: evaluation.outputs.sohImpactDelta,
        healthScore: evaluation.outputs.healthScore,
        healthLabel: evaluation.outputs.healthLabel,
        rulDaysShift: evaluation.outputs.rulDaysShift,
        recommendationSummary: evaluation.outputs.recommendationSummary
      }
    },
    evaluation
  });

  return {
    baseline: payload.baseline,
    evaluation
  };
}

export async function getLearnBaselinePayload(planeId: string): Promise<BaselinePayload> {
  const now = Date.now();
  const cached = baselineCache.get(planeId);
  if (cached?.value && cached.expiresAt > now) {
    return cached.value;
  }
  if (cached?.promise) {
    return cached.promise;
  }

  const promise = computeLearnBaselinePayload(planeId)
    .then((value) => {
      baselineCache.set(planeId, {
        value,
        expiresAt: Date.now() + BASELINE_CACHE_TTL_MS
      });
      return value;
    })
    .catch((error) => {
      baselineCache.delete(planeId);
      throw error;
    });

  baselineCache.set(planeId, {
    expiresAt: now + BASELINE_CACHE_TTL_MS,
    promise
  });

  return promise;
}
