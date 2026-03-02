import { cn } from "@/lib/utils";
import { ReactNode } from "react";

type BadgeTone = "ok" | "warn" | "risk" | "neutral";

const toneClassMap: Record<BadgeTone, string> = {
  ok: "bg-emerald-100 text-emerald-700 border-emerald-300",
  warn: "bg-amber-100 text-amber-700 border-amber-300",
  risk: "bg-rose-100 text-rose-700 border-rose-300",
  neutral: "bg-slate-100 text-slate-700 border-slate-300"
};

type Props = {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
};

export function Badge({ tone = "neutral", className, children }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium",
        toneClassMap[tone],
        className
      )}
    >
      {children}
    </span>
  );
}
