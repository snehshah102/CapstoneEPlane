import Link from "next/link";

import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function ExperiencePage() {
  return (
    <main className="space-y-8 pb-10">
      <section className="space-y-3 pt-6">
        <p className="text-sm font-medium uppercase tracking-[0.16em] text-slate-500">
          AeroCell Walkthrough
        </p>
        <h1 className="section-title text-slate-900">Experience Overview</h1>
        <p className="max-w-3xl text-sm leading-relaxed text-slate-600">
          This overview page gives presenters a quick path through the live battery
          analytics experience, from fleet context to plane-level health, forecasting,
          and recommendation guidance.
        </p>
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <Card className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted">Step 1</p>
          <h2 className="font-[var(--font-heading)] text-xl text-slate-900">Fleet View</h2>
          <p className="text-sm text-slate-600">
            Start on the planes page to compare live SOH, trend, and activity across the fleet.
          </p>
        </Card>
        <Card className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted">Step 2</p>
          <h2 className="font-[var(--font-heading)] text-xl text-slate-900">Plane Dashboard</h2>
          <p className="text-sm text-slate-600">
            Open a specific aircraft to review live health signals, forecasted decline, weather,
            cost, and recommendation windows.
          </p>
        </Card>
        <Card className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted">Step 3</p>
          <h2 className="font-[var(--font-heading)] text-xl text-slate-900">Learning Layer</h2>
          <p className="text-sm text-slate-600">
            Use the Learn page to explain what operational decisions change battery wear and why.
          </p>
        </Card>
      </section>

      <Card className="space-y-3">
        <h2 className="font-[var(--font-heading)] text-2xl text-slate-900">
          How to Read This Page
        </h2>
        <p className="text-sm leading-relaxed text-slate-600">
          Use this page as a presenter guide. Move from high-level fleet status into one plane’s
          live dashboard, then finish with the educational simulator if you want to explain the
          battery concepts behind the recommendations.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link href="/planes">
            <Button>Open Planes</Button>
          </Link>
          <Link href="/learn">
            <Button className="bg-white text-slate-900 ring-1 ring-slate-300 hover:bg-slate-50">
              Open Learn
            </Button>
          </Link>
        </div>
      </Card>
    </main>
  );
}
