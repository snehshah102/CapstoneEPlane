"use client";

import { GlossaryItem } from "@/lib/contracts/schemas";
import { Card } from "@/components/ui/card";

type Props = {
  title?: string;
  subtitle?: string;
  items: GlossaryItem[];
};

export function GlossarySection({
  title = "Quick Glossary",
  subtitle = "Key terms used on this page.",
  items
}: Props) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="font-[var(--font-heading)] text-2xl text-slate-900">{title}</h2>
        <p className="text-sm text-muted">{subtitle}</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <Card key={item.id} className="space-y-1">
            <p className="text-sm font-semibold text-slate-900">{item.term}</p>
            <p className="text-xs text-muted">{item.plainLanguage}</p>
            <p className="text-xs text-blue-700">{item.whyItMatters}</p>
          </Card>
        ))}
      </div>
    </section>
  );
}
