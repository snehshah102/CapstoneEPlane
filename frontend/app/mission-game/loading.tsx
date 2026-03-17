export default function MissionGameLoading() {
  return (
    <main className="space-y-6">
      <section className="space-y-2">
        <div className="h-10 w-40 animate-pulse rounded-2xl bg-slate-200/80" />
        <div className="h-5 w-[30rem] max-w-full animate-pulse rounded-xl bg-slate-100" />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <div className="rounded-3xl border border-slate-200/90 bg-gradient-to-b from-white to-slate-50/60 p-6 shadow-glass">
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="h-12 animate-pulse rounded-xl bg-slate-100" />
            ))}
            <div className="h-11 w-36 animate-pulse rounded-full bg-blue-100" />
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-3xl border border-slate-200/90 bg-gradient-to-b from-white to-slate-50/60 p-6 shadow-glass">
            <div className="h-6 w-44 animate-pulse rounded-xl bg-slate-200/80" />
            <div className="mt-4 h-24 animate-pulse rounded-2xl bg-slate-100" />
          </div>
          <div className="rounded-3xl border border-slate-200/90 bg-gradient-to-b from-white to-slate-50/60 p-6 shadow-glass">
            <div className="h-6 w-36 animate-pulse rounded-xl bg-slate-200/80" />
            <div className="mt-4 grid gap-3">
              {Array.from({ length: 3 }).map((_, index) => (
                <div key={index} className="h-11 animate-pulse rounded-xl bg-slate-100" />
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
