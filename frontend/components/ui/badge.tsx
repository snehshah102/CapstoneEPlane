import { cn } from "@/lib/utils";
import { ReactNode } from "react";

type BadgeTone = "ok" | "warn" | "risk" | "neutral";

const toneClassMap: Record<BadgeTone, string> = {
  ok: "bg-ok/20 text-ok border-ok/35",
  warn: "bg-warn/20 text-warn border-warn/35",
  risk: "bg-risk/20 text-risk border-risk/35",
  neutral: "bg-slate-500/20 text-slate-200 border-slate-500/35"
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
