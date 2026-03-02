"use client";

import { Info } from "lucide-react";
import { useState } from "react";

type Props = {
  term: string;
  plainLanguage: string;
  whyItMatters: string;
  technicalDetail?: string;
  className?: string;
};

export function InfoTooltip({
  term,
  plainLanguage,
  whyItMatters,
  technicalDetail,
  className
}: Props) {
  const [open, setOpen] = useState(false);
  const [deepDive, setDeepDive] = useState(false);

  return (
    <span className={`relative inline-flex items-center ${className ?? ""}`}>
      <button
        type="button"
        aria-label={`About ${term}`}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-500/60 text-slate-300 transition hover:border-cyan-300 hover:text-cyan-200"
      >
        <Info size={12} />
      </button>
      {open ? (
        <div
          role="dialog"
          className="absolute left-6 top-0 z-50 w-72 rounded-xl border border-slate-500/40 bg-slate-900/95 p-3 text-left shadow-glass"
        >
          <p className="font-semibold text-slate-100">{term}</p>
          <p className="mt-1 text-xs text-slate-300">{plainLanguage}</p>
          <p className="mt-1 text-xs text-cyan-200">{whyItMatters}</p>
          {technicalDetail ? (
            <div className="mt-2">
              <button
                type="button"
                className="text-xs text-slate-300 underline decoration-dotted hover:text-white"
                onClick={() => setDeepDive((value) => !value)}
              >
                {deepDive ? "Hide Deep Dive" : "Show Deep Dive"}
              </button>
              {deepDive ? (
                <p className="mt-1 text-xs text-slate-400">{technicalDetail}</p>
              ) : null}
            </div>
          ) : null}
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="mt-2 text-xs text-slate-400 underline decoration-dotted hover:text-slate-200"
          >
            Close
          </button>
        </div>
      ) : null}
    </span>
  );
}
