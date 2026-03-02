import { GlossaryItem } from "@/lib/contracts/schemas";

export const GLOSSARY_FALLBACK: GlossaryItem[] = [
  {
    id: "soh",
    term: "State of Health (SOH)",
    plainLanguage:
      "How healthy the battery is compared to when it was new, shown as a percent.",
    whyItMatters:
      "Lower SOH means reduced endurance and potentially faster degradation."
  },
  {
    id: "trend_points",
    term: "Trend Points",
    plainLanguage: "The change in SOH over a selected time window.",
    whyItMatters:
      "Negative points mean battery health is declining over time."
  },
  {
    id: "confidence",
    term: "Confidence",
    plainLanguage:
      "How certain the model is that a prediction or recommendation is reliable.",
    whyItMatters:
      "Higher confidence means you can trust the recommendation more."
  },
  {
    id: "rul",
    term: "Remaining Useful Life (RUL)",
    plainLanguage:
      "Estimated days and cycles before replacement becomes recommended.",
    whyItMatters:
      "Helps schedule maintenance before issues become operational."
  },
  {
    id: "risk",
    term: "Health Label",
    plainLanguage: "A friendly status: Healthy, Watch, or Critical.",
    whyItMatters:
      "Turns raw model outputs into clear action guidance for students."
  },
  {
    id: "calendar_score",
    term: "Flight Day Score",
    plainLanguage:
      "How suitable a date is for minimizing battery wear during operations.",
    whyItMatters:
      "Higher scores generally indicate lower expected wear."
  },
  {
    id: "charge_window",
    term: "Charge Window",
    plainLanguage: "Suggested charging time before the selected flight day.",
    whyItMatters:
      "Charging too early and holding high SOC can accelerate wear."
  }
];

export function glossaryById(items: GlossaryItem[]) {
  return new Map(items.map((item) => [item.id, item]));
}
