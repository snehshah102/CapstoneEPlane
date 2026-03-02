import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPct(value: number) {
  return `${value.toFixed(1)}%`;
}

export function riskLabel(value: number) {
  if (value >= 75) return "low";
  if (value >= 55) return "medium";
  return "high";
}
