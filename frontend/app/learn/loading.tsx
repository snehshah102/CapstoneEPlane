export default function LearnLoading() {
  return (
    <main className="space-y-6">
      <section className="space-y-2">
        <div className="h-10 w-64 animate-pulse rounded-2xl bg-slate-200/80" />
        <div className="h-5 w-[28rem] max-w-full animate-pulse rounded-xl bg-slate-100" />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-3xl border border-slate-200/90 bg-gradient-to-b from-white to-slate-50/60 p-6 shadow-glass">
          <div className="grid gap-3 md:grid-cols-2">
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="rounded-xl border border-stone-200 bg-white/75 p-3">
                <div className="h-4 w-32 animate-pulse rounded bg-slate-200/80" />
                <div className="mt-4 h-3 w-full animate-pulse rounded-full bg-slate-100" />
                <div className="mt-3 h-5 w-10 animate-pulse rounded bg-slate-200/80" />
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-3xl border border-slate-200/90 bg-gradient-to-b from-white to-slate-50/60 p-6 shadow-glass">
          <div className="h-7 w-52 animate-pulse rounded-xl bg-slate-200/80" />
          <div className="mt-4 h-2.5 w-full animate-pulse rounded-full bg-slate-100" />
          <div className="mt-4 grid gap-2">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="h-12 animate-pulse rounded-xl bg-slate-50" />
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
