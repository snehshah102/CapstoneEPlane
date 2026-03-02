"use client";

import { Info } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

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
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });

  const updatePosition = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPosition({
      top: rect.bottom + 10,
      left: Math.max(16, rect.left - 140)
    });
  };

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    updatePosition();
    const onViewportChange = () => updatePosition();
    window.addEventListener("scroll", onViewportChange, true);
    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("scroll", onViewportChange, true);
      window.removeEventListener("resize", onViewportChange);
    };
  }, [open]);

  const tooltip = open ? (
    <div
      role="tooltip"
      className="fixed z-[1100] w-[280px] rounded-2xl border border-stone-300 bg-white p-3 text-left shadow-2xl"
      style={{ top: position.top, left: position.left }}
    >
      <p className="font-semibold text-slate-900">{term}</p>
      <p className="mt-1 text-xs text-slate-700">{plainLanguage}</p>
      <p className="mt-1 text-xs text-blue-700">{whyItMatters}</p>
      {technicalDetail ? (
        <p className="mt-1 text-[11px] text-slate-500">{technicalDetail}</p>
      ) : null}
    </div>
  ) : null;

  return (
    <>
      <span className={`inline-flex items-center ${className ?? ""}`}>
        <button
          ref={triggerRef}
          type="button"
          aria-label={`About ${term}`}
          onMouseEnter={() => {
            updatePosition();
            setOpen(true);
          }}
          onMouseLeave={() => setOpen(false)}
          onFocus={() => {
            updatePosition();
            setOpen(true);
          }}
          onBlur={() => setOpen(false)}
          className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-stone-300 text-slate-500 transition hover:border-blue-300 hover:text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
        >
          <Info size={12} />
        </button>
      </span>
      {mounted && tooltip ? createPortal(tooltip, document.body) : null}
    </>
  );
}
