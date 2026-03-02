import { cn } from "@/lib/utils";
import { HTMLAttributes } from "react";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-3xl border border-slate-200/90 bg-gradient-to-b from-white to-slate-50/60 p-6 shadow-glass transition duration-200 hover:shadow-[0_18px_42px_rgba(15,23,42,0.08)]",
        className
      )}
      {...props}
    />
  );
}
