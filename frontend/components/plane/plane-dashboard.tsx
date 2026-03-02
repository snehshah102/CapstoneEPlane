"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { addMonths, endOfMonth, formatISO, startOfMonth } from "date-fns";
import { BatteryMedium, CalendarClock, Gauge, Sparkles } from "lucide-react";

import {
  getGlossary,
  getPlaneFlights,
  getPlaneHealth,
  getPlanePrediction,
  getPlaneRecommendations,
  getPlaneTrend,
  getWeather
} from "@/lib/adapters/api-client";
import { airportFromLabel } from "@/lib/airports";
import { SohLineChart } from "@/components/charts/soh-line-chart";
import { WearScatterChart } from "@/components/charts/wear-scatter-chart";
import { RecommendationCalendar } from "@/components/plane/recommendation-calendar";
import { RouteMap } from "@/components/plane/route-map";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { GlossaryDrawer } from "@/components/ui/glossary-drawer";
import { HealthMeter } from "@/components/ui/health-meter";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { GLOSSARY_FALLBACK } from "@/lib/glossary";
import { formatPct } from "@/lib/utils";

function monthString(date: Date) {
  return date.toISOString().slice(0, 7);
}

function monthRange(month: string) {
  const [y, m] = month.split("-").map(Number);
  const start = new Date(Date.UTC(y, m - 1, 1));
  const end = endOfMonth(start);
  return {
    start: formatISO(startOfMonth(start), { representation: "date" }),
    end: formatISO(end, { representation: "date" })
  };
}

function monthOptions() {
  return Array.from({ length: 4 }).map((_, index) =>
    monthString(addMonths(new Date(), index))
  );
}

type Props = {
  planeId: string;
};

export function PlaneDashboard({ planeId }: Props) {
  const [month, setMonth] = useState(monthString(new Date()));
  const [selectedGlossaryId, setSelectedGlossaryId] = useState<string | null>(
    "risk"
  );
  const options = useMemo(() => monthOptions(), []);

  const healthQuery = useQuery({
    queryKey: ["plane-health", planeId],
    queryFn: () => getPlaneHealth(planeId)
  });
  const trendQuery = useQuery({
    queryKey: ["plane-trend", planeId, "90d"],
    queryFn: () => getPlaneTrend(planeId, "90d")
  });
  const flightsQuery = useQuery({
    queryKey: ["plane-flights", planeId],
    queryFn: () => getPlaneFlights(planeId, 20)
  });
  const predictionQuery = useQuery({
    queryKey: ["plane-prediction", planeId],
    queryFn: () => getPlanePrediction(planeId)
  });
  const recsQuery = useQuery({
    queryKey: ["plane-recs", planeId, month],
    queryFn: () => getPlaneRecommendations(planeId, month)
  });
  const glossaryQuery = useQuery({
    queryKey: ["glossary"],
    queryFn: getGlossary
  });

  const airportCode =
    healthQuery.data?.health.lastFlight.departureAirport?.slice(0, 4) ?? "CYKF";
  const { start, end } = monthRange(month);
  const weatherQuery = useQuery({
    queryKey: ["weather", airportCode, start, end],
    queryFn: () => getWeather(airportCode, start, end)
  });

  if (
    healthQuery.isLoading ||
    trendQuery.isLoading ||
    flightsQuery.isLoading ||
    predictionQuery.isLoading ||
    recsQuery.isLoading
  ) {
    return <div className="text-sm text-slate-300">Loading plane dashboard...</div>;
  }

  if (
    healthQuery.isError ||
    trendQuery.isError ||
    flightsQuery.isError ||
    predictionQuery.isError ||
    recsQuery.isError ||
    !healthQuery.data ||
    !trendQuery.data ||
    !flightsQuery.data ||
    !predictionQuery.data ||
    !recsQuery.data
  ) {
    return <div className="text-sm text-rose-300">Unable to load full plane snapshot data.</div>;
  }

  const glossaryItems = glossaryQuery.data?.items ?? GLOSSARY_FALLBACK;
  const { health } = healthQuery.data;
  const { prediction } = predictionQuery.data;
  const flights = flightsQuery.data.flights;
  const recommendations = recsQuery.data.recommendations;
  const departure = airportFromLabel(health.lastFlight.departureAirport);
  const destination = airportFromLabel(health.lastFlight.destinationAirport);

  const trendSummary =
    health.sohTrend30 < 0
      ? "SOH is trending downward (normal aging behavior)."
      : "SOH trend is stable or improving in this window.";

  return (
    <main className="space-y-5 pb-28">
      <section>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-[var(--font-heading)] text-3xl">Plane {planeId} Dashboard</h1>
            <p className="text-sm text-slate-300">
              Updated {new Date(health.updatedAt).toLocaleString()} | Live polling
              every 45s
            </p>
          </div>
          <p className="rounded-full border border-slate-500/40 bg-slate-900/40 px-3 py-1 text-xs text-slate-200">
            Friendly mode: student-ready explanations enabled
          </p>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card className="space-y-3">
          <HealthMeter
            score={health.healthScore}
            label={health.healthLabel}
            explanation={health.healthExplanation}
          />
          <p className="text-xs text-slate-400">
            This replaces ambiguous risk colors with a plain-language meter.
          </p>
        </Card>
        <Card className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-slate-400">How to read key numbers</p>
          <p className="text-sm text-slate-300">
            `SOH` is current battery condition, `Trend pts` shows direction over
            time, and `Confidence` indicates how reliable a model result is.
          </p>
          <button
            type="button"
            onClick={() => setSelectedGlossaryId("soh")}
            className="rounded-lg border border-slate-600/30 px-3 py-2 text-left text-xs text-slate-300"
          >
            Open glossary focus: SOH
          </button>
        </Card>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card
          className="space-y-1 cursor-pointer"
          onClick={() => setSelectedGlossaryId("soh")}
        >
          <p className="text-xs uppercase tracking-wide text-slate-400">
            Current SOH{" "}
            <InfoTooltip
              term="SOH"
              plainLanguage="Battery health compared to when it was new."
              whyItMatters="Lower SOH typically means less usable endurance."
            />
          </p>
          <p className="text-2xl font-semibold">{formatPct(health.sohCurrent)}</p>
          <p className="text-xs text-slate-400">
            Blend target confidence {health.confidence.toFixed(2)}
          </p>
        </Card>
        <Card
          className="space-y-1 cursor-pointer"
          onClick={() => setSelectedGlossaryId("trend_points")}
        >
          <p className="text-xs uppercase tracking-wide text-slate-400">
            SOH Trend{" "}
            <InfoTooltip
              term="Trend Points"
              plainLanguage="How SOH changed over the selected period."
              whyItMatters="Negative values mean wear is progressing."
            />
          </p>
          <p className="text-2xl font-semibold">
            {health.sohTrend30.toFixed(2)} / {health.sohTrend90.toFixed(2)}
          </p>
          <p className="text-xs text-slate-400">30d / 90d change (pts)</p>
          <p className="text-xs text-cyan-200">{trendSummary}</p>
        </Card>
        <Card
          className="space-y-1 cursor-pointer"
          onClick={() => setSelectedGlossaryId("confidence")}
        >
          <p className="text-xs uppercase tracking-wide text-slate-400">
            Replacement Date{" "}
            <InfoTooltip
              term="Replacement Forecast"
              plainLanguage="Estimated date when replacement becomes recommended."
              whyItMatters="Supports maintenance planning before battery stress becomes critical."
            />
          </p>
          <p className="text-2xl font-semibold">
            {new Date(prediction.forecast.replacementDatePred).toLocaleDateString()}
          </p>
          <p className="text-xs text-slate-400">
            Model confidence {prediction.forecast.confidence.toFixed(2)}
          </p>
        </Card>
        <Card
          className="space-y-1 cursor-pointer"
          onClick={() => setSelectedGlossaryId("rul")}
        >
          <p className="text-xs uppercase tracking-wide text-slate-400">
            Remaining Useful Life{" "}
            <InfoTooltip
              term="RUL"
              plainLanguage="Estimated battery life left in days and cycles."
              whyItMatters="Helps avoid last-minute operational disruptions."
            />
          </p>
          <p className="text-2xl font-semibold">
            {prediction.forecast.rulDaysPred}d / {prediction.forecast.rulCyclesPred} cycles
          </p>
          <p className="text-xs text-slate-400">Predicted through wear trajectory model</p>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1fr_1fr_1fr]">
        <Card>
          <div className="mb-3 flex items-center gap-2">
            <Gauge className="h-4 w-4 text-cyan-300" />
            <h2 className="font-[var(--font-heading)] text-lg">Live Battery Health</h2>
          </div>
          <p className="mb-3 text-xs text-slate-400">Subtitle: live telemetry for current pack condition.</p>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-slate-400">Pack Voltage</p>
              <p className="font-semibold">{health.pack.voltage.toFixed(1)} V</p>
            </div>
            <div>
              <p className="text-slate-400">Pack Current</p>
              <p className="font-semibold">{health.pack.current.toFixed(1)} A</p>
            </div>
            <div>
              <p className="text-slate-400">Pack Temp Avg</p>
              <p className="font-semibold">{health.pack.tempAvg.toFixed(1)} C</p>
            </div>
            <div>
              <p className="text-slate-400">Pack SOC</p>
              <p className="font-semibold">{health.pack.soc.toFixed(1)}%</p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="mb-3 flex items-center gap-2">
            <BatteryMedium className="h-4 w-4 text-emerald-300" />
            <h2 className="font-[var(--font-heading)] text-lg">Last Flight Summary</h2>
          </div>
          <p className="mb-3 text-xs text-slate-400">Subtitle: context from the most recent flight event.</p>
          <div className="space-y-2 text-sm">
            <p>
              Flight ID: <span className="font-semibold">{health.lastFlight.flightId}</span>
            </p>
            <p>
              Route: <span className="font-semibold">{health.lastFlight.route}</span>
            </p>
            <p>
              Date:{" "}
              <span className="font-semibold">
                {new Date(health.lastFlight.eventDate).toLocaleDateString()}
              </span>
            </p>
            <p>
              Duration:{" "}
              <span className="font-semibold">{health.lastFlight.durationMin ?? 0} min</span>
            </p>
          </div>
        </Card>

        <Card>
          <div className="mb-3 flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-amber-300" />
            <h2 className="font-[var(--font-heading)] text-lg">Forecast Snapshot</h2>
          </div>
          <p className="mb-3 text-xs text-slate-400">Subtitle: model label sources and blended target.</p>
          <div className="space-y-3 text-sm">
            <p>
              SOH Proxy: <span className="font-semibold">{prediction.sohProxyPoh.toFixed(2)}%</span>
            </p>
            <p>
              SOH Observed Norm:{" "}
              <span className="font-semibold">{prediction.sohObservedNorm.toFixed(2)}%</span>
            </p>
            <p>
              SOH Blend Target:{" "}
              <span className="font-semibold">{prediction.sohTargetBlend.toFixed(2)}%</span>
            </p>
          </div>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Card>
          <h2 className="mb-1 font-[var(--font-heading)] text-lg">SOH History (90d)</h2>
          <p className="mb-3 text-xs text-slate-400">Subtitle: trend of battery health over recent flights.</p>
          <SohLineChart points={trendQuery.data.points} />
        </Card>
        <Card>
          <h2 className="mb-1 font-[var(--font-heading)] text-lg">Charging vs Flight Wear</h2>
          <p className="mb-3 text-xs text-slate-400">Subtitle: relationship between mission profile and wear score.</p>
          <WearScatterChart flights={flights} />
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-cyan-300" />
              <h2 className="font-[var(--font-heading)] text-lg">Flight Recommendation System</h2>
            </div>
            <label className="text-sm text-slate-300">
              Month{" "}
              <select
                value={month}
                onChange={(event) => setMonth(event.target.value)}
                className="ml-2 rounded-lg border border-slate-600/50 bg-slate-950/50 px-2 py-1"
              >
                {options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="space-y-2 rounded-xl border border-slate-600/35 bg-slate-950/25 p-3 text-sm">
            <h3 className="font-semibold text-slate-100">Why this month is scored this way</h3>
            <p className="text-xs text-slate-300">
              Scores blend weather suitability, thermal stress, projected battery stress,
              and charging timing effects. Click a calendar day to inspect these factors.
            </p>
          </div>

          <div className="space-y-2 rounded-xl border border-slate-600/35 bg-slate-950/25 p-3">
            <h3 className="font-semibold text-slate-100">Best days to fly</h3>
            <p className="text-xs text-slate-400">
              Top-ranked days for lower expected battery wear.
            </p>
            <div className="grid gap-2 md:grid-cols-2">
              {recommendations.flightDayScores.slice(0, 6).map((day) => (
                <button
                  type="button"
                  key={day.date}
                  onClick={() => setSelectedGlossaryId("calendar_score")}
                  className="rounded-lg border border-slate-600/30 p-3 text-left text-sm"
                >
                  <div className="flex items-center justify-between">
                    <p>{day.date}</p>
                    <Badge
                      tone={
                        day.confidenceTier === "high"
                          ? "ok"
                          : day.confidenceTier === "medium"
                            ? "warn"
                            : "risk"
                      }
                    >
                      {day.confidenceTier}
                    </Badge>
                  </div>
                  <p className="mt-1 font-semibold text-cyan-200">Score {day.score.toFixed(1)}</p>
                  <p className="text-xs text-slate-400">{day.weatherSummary}</p>
                </button>
              ))}
            </div>
          </div>

          <div
            className="space-y-2 rounded-xl border border-slate-600/35 bg-slate-950/25 p-3"
            onClick={() => setSelectedGlossaryId("calendar_score")}
          >
            <h3 className="font-semibold text-slate-100">Calendar view: every day of the month</h3>
            <p className="text-xs text-slate-400">
              Click any date to see score breakdown, confidence, and battery-friendly guidance.
            </p>
            <RecommendationCalendar
              days={recommendations.calendarDays}
              breakdownByDate={recommendations.scoreBreakdownByDate}
            />
          </div>

          <div
            className="space-y-2 rounded-xl border border-slate-600/35 bg-slate-950/25 p-3"
            onClick={() => setSelectedGlossaryId("charge_window")}
          >
            <h3 className="font-semibold text-slate-100">Charge timing to reduce wear</h3>
            <p className="text-xs text-slate-400">
              Keep high SOC idle time short by charging closer to departure.
            </p>
            <div className="grid gap-3 md:grid-cols-2">
              {recommendations.chargePlan.map((plan) => (
                <div
                  key={`${plan.date}-${plan.chargeWindowStart}`}
                  className="rounded-lg border border-emerald-500/25 bg-emerald-900/10 p-3 text-sm"
                >
                  <p className="font-semibold text-emerald-200">{plan.date}</p>
                  <p>Target SOC: {plan.targetSoc}%</p>
                  <p>
                    Charge window: {plan.chargeWindowStart} - {plan.chargeWindowEnd}
                  </p>
                  <p className="mt-1 text-xs text-slate-300">{plan.rationale}</p>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card className="space-y-4">
          <h2 className="font-[var(--font-heading)] text-lg">Route + Weather Context</h2>
          {weatherQuery.data?.demoMode ? (
            <div className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              Demo mode active: using fallback-modeled weather for reliability.
            </div>
          ) : null}
          <RouteMap
            departure={
              departure
                ? { lat: departure.lat, lon: departure.lon, label: departure.name }
                : null
            }
            destination={
              destination
                ? { lat: destination.lat, lon: destination.lon, label: destination.name }
                : null
            }
          />
          <div className="space-y-2 text-sm">
            <p className="text-slate-300">
              Weather runway ({airportCode}) | Source mode:{" "}
              <span className="font-semibold capitalize">
                {weatherQuery.data?.mode ?? "unknown"}
              </span>
            </p>
            {weatherQuery.data?.days.slice(0, 5).map((day) => (
              <div key={day.date} className="flex items-center justify-between rounded-lg border border-slate-600/30 px-3 py-2 text-xs">
                <span>{day.date}</span>
                <span>
                  {day.tempMinC.toFixed(0)}-{day.tempMaxC.toFixed(0)}C
                </span>
                <span>{day.precipMm.toFixed(1)}mm</span>
                <Badge
                  tone={
                    day.confidenceTier === "high"
                      ? "ok"
                      : day.confidenceTier === "medium"
                        ? "warn"
                        : "risk"
                  }
                >
                  {day.confidenceTier}
                </Badge>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <GlossaryDrawer
        items={glossaryItems}
        selectedId={selectedGlossaryId}
        title="Pinned Glossary"
      />
    </main>
  );
}
