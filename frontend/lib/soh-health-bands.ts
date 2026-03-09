export type RiskBand = "low" | "medium" | "watch" | "critical";
export type HealthLabel = "healthy" | "medium" | "watch" | "critical";

function safeNumber(value: unknown): number | null {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

export function riskBandFromSoh(soh: unknown): RiskBand {
  const num = safeNumber(soh);
  if (num === null) {
    return "critical";
  }
  if (num >= 80) {
    return "low";
  }
  if (num >= 40) {
    return "medium";
  }
  if (num >= 20) {
    return "watch";
  }
  return "critical";
}

export function healthLabelFromRiskBand(riskBand: RiskBand): HealthLabel {
  if (riskBand === "low") {
    return "healthy";
  }
  if (riskBand === "medium") {
    return "medium";
  }
  if (riskBand === "watch") {
    return "watch";
  }
  return "critical";
}

export function healthExplanationFromLabel(label: HealthLabel): string {
  if (label === "healthy") {
    return "Battery condition is healthy in the adjusted SOH scale.";
  }
  if (label === "medium") {
    return "Battery is in the medium band; monitor stress and charging patterns.";
  }
  if (label === "watch") {
    return "Battery is in the watch band; reduce stress and plan maintenance.";
  }
  return "Battery is in the critical band; minimize stress and prioritize replacement planning.";
}
