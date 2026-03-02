"use client";

import { BookOpen, Pin, PinOff } from "lucide-react";
import { useState } from "react";

import { GlossaryItem } from "@/lib/contracts/schemas";
import { cn } from "@/lib/utils";

type Props = {
  items: GlossaryItem[];
  selectedId?: string | null;
  title?: string;
};

export function GlossaryDrawer({ items, selectedId, title = "Glossary" }: Props) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(true);

  const selected = selectedId
    ? items.find((item) => item.id === selectedId) ?? null
    : null;

  return (
    <aside
      className={cn(
        "glass fixed bottom-4 right-4 z-40 w-[320px] rounded-2xl border border-slate-500/40 p-4 transition",
        open || pinned ? "translate-y-0 opacity-100" : "translate-y-3 opacity-85"
      )}
    >
      <div className="mb-3 flex items-center justify-between">
        <p className="inline-flex items-center gap-2 font-[var(--font-heading)] text-sm">
          <BookOpen size={14} />
          {title}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPinned((value) => !value)}
            className="rounded-md border border-slate-500/50 p-1 text-slate-300 transition hover:text-white"
            aria-label={pinned ? "Unpin glossary drawer" : "Pin glossary drawer"}
          >
            {pinned ? <PinOff size={14} /> : <Pin size={14} />}
          </button>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="rounded-md border border-slate-500/50 px-2 py-1 text-xs text-slate-300 transition hover:text-white"
          >
            {open ? "Collapse" : "Expand"}
          </button>
        </div>
      </div>

      {open || pinned ? (
        <div className="space-y-2">
          {selected ? (
            <div className="rounded-lg border border-cyan-400/40 bg-cyan-400/10 p-2">
              <p className="text-xs font-semibold text-cyan-100">{selected.term}</p>
              <p className="mt-1 text-xs text-slate-300">{selected.plainLanguage}</p>
            </div>
          ) : null}
          <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
            {items.map((item) => (
              <div
                key={item.id}
                className={cn(
                  "rounded-lg border border-slate-600/40 p-2",
                  selectedId === item.id
                    ? "border-cyan-400/50 bg-cyan-400/10"
                    : "bg-slate-950/25"
                )}
              >
                <p className="text-xs font-semibold text-slate-100">{item.term}</p>
                <p className="text-xs text-slate-300">{item.whyItMatters}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </aside>
  );
}
