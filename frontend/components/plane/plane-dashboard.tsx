"use client";

import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  addMonths,
} from "date-fns";
import {
  BatteryMedium,
  CalendarClock,
  Gauge,
  Sparkles,
  TrendingUp,
  Zap
} from "lucide-react";

import {
  getChargingCost,
  getGlossary,
  getPlaneHealth,
  getPlanePrediction,
  getPlaneRecommendations,
  getPlaneTrend,
  getWeather
} from "@/lib/adapters/api-client";
import { airportFromLabel } from "@/lib/airports";
import { RangeEnduranceChart } from "@/components/charts/range-endurance-chart";
import { SohLineChart } from "@/components/charts/soh-line-chart";
import { RecommendationCalendar } from "@/components/plane/recommendation-calendar";
import { RouteMap } from "@/components/plane/route-map";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { GlossarySection } from "@/components/ui/glossary-section";
import { HealthMeter } from "@/components/ui/health-meter";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { GLOSSARY_FALLBACK } from "@/lib/glossary";
import { ForecastCurvePoint } from "@/lib/contracts/schemas";
import { formatPct } from "@/lib/utils";

function monthString(date: Date) {
  return date.toISOString().slice(0, 7);
}

function formatFixedValue(value: number | null | undefined, digits: number) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function monthRange(month: string) {
  const [y, m] = month.split("-").map(Number);
  return {
    start: `${y}-${String(m).padStart(2, "0")}-01`,
    end: new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10)
  };
}

function monthOptions() {
  return Array.from({ length: 4 }).map((_, index) =>
    monthString(addMonths(new Date(), index))
  );
}

const TREND_WINDOWS: Array<{ value: "30d" | "90d" | "1y" | "full"; label: string }> = [
  { value: "30d", label: "30d" },
  { value: "90d", label: "90d" },
  { value: "1y", label: "1y" },
  { value: "full", label: "Full" }
];

type Props = {
  planeId: string;
};

type ForecastPoint = {
  date: string;
  soh: number;
};

function filterForecastPoints(
  forecastPoints: ForecastCurvePoint[],
  window: "30d" | "90d" | "1y" | "full"
): ForecastPoint[] {
  if (!forecastPoints.length) {
    return [];
  }
  if (window === "full") return forecastPoints;
  const forecastWindowDays = window === "30d" ? 30 : window === "90d" ? 90 : 365;
  const startDate = Date.parse(`${forecastPoints[0].date}T00:00:00Z`);
  return forecastPoints.filter((point) => {
    const pointDate = Date.parse(`${point.date}T00:00:00Z`);
    return Number.isFinite(pointDate) && pointDate - startDate <= forecastWindowDays * 86_400_000;
  });
}

function defaultRecommendationDate(month: string, availableDates: string[]) {
  if (!availableDates.length) {
    return null;
  }
  const today = new Date().toISOString().slice(0, 10);
  if (today.startsWith(month) && availableDates.includes(today)) {
    return today;
  }
  return availableDates[0];
}

export function PlaneDashboard({ planeId }: Props) {
  const [month, setMonth] = useState(monthString(new Date()));
  const [trendWindow, setTrendWindow] = useState<"30d" | "90d" | "1y" | "full">("90d");
  const [selectedRecommendationDate, setSelectedRecommendationDate] = useState<string | null>(null);
  const options = useMemo(() => monthOptions(), []);

  const healthQuery = useQuery({
    queryKey: ["plane-health", planeId],
    queryFn: () => getPlaneHealth(planeId),
    placeholderData: keepPreviousData,
    refetchInterval: 45_000
  });
  const trendQuery = useQuery({
    queryKey: ["plane-trend", planeId, trendWindow],
    queryFn: () => getPlaneTrend(planeId, trendWindow),
    placeholderData: keepPreviousData
  });
  const predictionQuery = useQuery({
    queryKey: ["plane-prediction", planeId],
    queryFn: () => getPlanePrediction(planeId),
    placeholderData: keepPreviousData
  });
  const recsQuery = useQuery({
    queryKey: ["plane-recs", planeId, month],
    queryFn: () => getPlaneRecommendations(planeId, month),
    placeholderData: keepPreviousData
  });
  const glossaryQuery = useQuery({
    queryKey: ["glossary"],
    queryFn: getGlossary
  });
  const forecastPoints = useMemo(() => {
    return filterForecastPoints(
      predictionQuery.data?.prediction.forecastCurve ?? [],
      trendWindow
    );
  }, [
    predictionQuery.data?.prediction.forecastCurve,
    trendWindow
  ]);

  const airportCode =
    healthQuery.data?.health.lastFlight.departureAirport?.slice(0, 4) ?? "CYKF";
  const { start, end } = monthRange(month);
  const weatherQuery = useQuery({
    queryKey: ["weather", airportCode, start, end],
    queryFn: () => getWeather(airportCode, start, end),
    placeholderData: keepPreviousData
  });

  const chargingQuery = useQuery({
    queryKey: ["plane-charging", planeId, airportCode],
    queryFn: () =>
      getChargingCost(airportCode, new Date().toISOString().slice(0, 10), 52),
    enabled: Boolean(airportCode),
    placeholderData: keepPreviousData
  });
  const recommendationDays = useMemo(
    () => recsQuery.data?.recommendations.calendarDays ?? [],
    [recsQuery.data?.recommendations.calendarDays]
  );
  const nextBestDay = useMemo(() => {
    if (!selectedRecommendationDate) {
      return null;
    }
    const remainingDays = recommendationDays.filter((day) => day.date > selectedRecommendationDate);
    if (!remainingDays.length) {
      return null;
    }
    return [...remainingDays].sort((a, b) => b.score - a.score)[0] ?? null;
  }, [recommendationDays, selectedRecommendationDate]);

  useEffect(() => {
    const availableDates = recommendationDays.map((day) => day.date);
    setSelectedRecommendationDate((current) => {
      if (current && availableDates.includes(current)) {
        return current;
      }
      return defaultRecommendationDate(month, availableDates);
    });
  }, [month, recommendationDays]);

  if (!healthQuery.data || !trendQuery.data || !predictionQuery.data || !recsQuery.data) {
    return <div className="text-sm text-muted">Loading plane dashboard...</div>;
  }

  if (
    (healthQuery.isError && !healthQuery.data) ||
    (trendQuery.isError && !trendQuery.data) ||
    (predictionQuery.isError && !predictionQuery.data) ||
    (recsQuery.isError && !recsQuery.data)
  ) {
    return <div className="text-sm text-rose-600">Unable to load plane data.</div>;
  }

  const glossaryItems = (glossaryQuery.data?.items ?? GLOSSARY_FALLBACK).filter(
    (item) =>
      ["soh", "rul", "confidence", "calendar_score", "charge_window"].includes(
        item.id
      )
  );
  const { health } = healthQuery.data;
  const { prediction } = predictionQuery.data;
  const recommendations = recsQuery.data.recommendations;
  const departure = airportFromLabel(health.lastFlight.departureAirport);
  const destination = airportFromLabel(health.lastFlight.destinationAirport);
  const chargingEstimate = chargingQuery.data?.estimate;
  const trendBusy = trendQuery.isFetching;
  const recommendationBusy = recsQuery.isFetching;
  const weatherBusy = weatherQuery.isFetching || chargingQuery.isFetching;
  const sessionCost = formatFixedValue(chargingEstimate?.estimatedSessionCostUsd, 2);
  const unitRate = formatFixedValue(chargingEstimate?.costPerKwhUsd, 3);

  return (
    <main className="space-y-6">
      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="section-title text-slate-900">Plane {planeId} Dashboard</h1>
            <p className="text-sm text-muted">
              Updated {new Date(health.updatedAt).toLocaleString()} | Polling every 45s
            </p>
          </div>
          <Badge
            tone={
              health.healthLabel === "healthy"
                ? "ok"
                : health.healthLabel === "medium"
                  ? "warn"
                  : health.healthLabel === "watch"
                    ? "risk"
                    : health.healthLabel === "decline"
                      ? "risk"
                  : "risk"
            }
          >
            {health.healthLabel}
          </Badge>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Card className="space-y-3 border-blue-200 bg-gradient-to-br from-blue-50 via-white to-blue-100/50">
          <p className="text-xs uppercase tracking-wide text-muted">
            Primary Metric: SOH{" "}
            <InfoTooltip
              term="SOH"
              plainLanguage="Battery condition compared to a new battery."
              whyItMatters="SOH is a leading indicator for endurance and maintenance timing."
            />
          </p>
          <p className="font-[var(--font-heading)] text-6xl text-slate-900">
            {formatPct(health.sohCurrent)}
          </p>
          <div className="h-2 overflow-hidden rounded-full bg-blue-100">
            <div
              className="h-full rounded-full bg-blue-600 transition-all duration-700"
              style={{ width: `${Math.max(0, Math.min(100, health.sohCurrent))}%` }}
            />
          </div>
          <p className="text-sm text-muted">
            30d: {health.sohTrend30.toFixed(2)} pts | 90d: {health.sohTrend90.toFixed(2)} pts
          </p>
          <div className="pt-2">
            <HealthMeter
              score={health.healthScore}
              label={health.healthLabel}
              explanation={health.healthExplanation}
            />
          </div>
        </Card>

        <Card className="space-y-3 border-stone-200 bg-gradient-to-br from-amber-50 via-white to-blue-50">
          <p className="text-xs uppercase tracking-wide text-muted">
            Primary Metric: RUL{" "}
            <InfoTooltip
              term="Remaining Useful Life (RUL)"
              plainLanguage="Estimated days and cycles before replacement is advised."
              whyItMatters="RUL helps plan service windows before disruption."
            />
          </p>
          <p className="font-[var(--font-heading)] text-6xl text-slate-900">
            {prediction.forecast.rulCyclesPred}
          </p>
          <p className="text-xl font-semibold text-slate-900">estimated flights remaining</p>
          <p className="text-sm text-muted">
            Confidence {prediction.forecast.confidence.toFixed(2)}
          </p>
        </Card>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted">Replacement Date</p>
          <p className="text-2xl font-semibold text-slate-900">
            {new Date(prediction.forecast.replacementDatePred).toLocaleDateString()}
          </p>
        </Card>
        <Card className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted">Current Charge</p>
          <p className="text-2xl font-semibold text-slate-900">
            {health.currentChargeSoc.toFixed(1)}%
          </p>
        </Card>
        <Card className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted">Time Since Last Flight</p>
          <p className="text-2xl font-semibold text-slate-900">
            {health.timeSinceLastFlightHours}h
          </p>
        </Card>
        <Card className="space-y-2">
          <p className="inline-flex items-center gap-1 text-xs uppercase tracking-wide text-muted">
            <Zap size={12} />
            Charging Cost
          </p>
          <p className="text-2xl font-semibold text-slate-900">
            ${sessionCost}
          </p>
          <p className="text-xs text-muted">
            {airportCode} {chargingEstimate ? `(${chargingEstimate.sourceMode})` : ""}
          </p>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1fr_1fr_1fr]">
        <Card>
          <div className="mb-3 flex items-center gap-2">
            <Gauge className="h-4 w-4 text-blue-700" />
            <h2 className="font-[var(--font-heading)] text-lg text-slate-900">Live Battery Health</h2>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm text-slate-800">
            <div>
              <p className="text-muted">Pack Voltage</p>
              <p className="font-semibold">{health.pack.voltage.toFixed(1)} V</p>
            </div>
            <div>
              <p className="text-muted">Pack Current</p>
              <p className="font-semibold">{health.pack.current.toFixed(1)} A</p>
            </div>
            <div>
              <p className="text-muted">Pack Temp Avg</p>
              <p className="font-semibold">{health.pack.tempAvg.toFixed(1)} C</p>
            </div>
            <div>
              <p className="text-muted">Pack SOC</p>
              <p className="font-semibold">{health.pack.soc.toFixed(1)}%</p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="mb-3 flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-blue-700" />
            <h2 className="font-[var(--font-heading)] text-lg text-slate-900">Last Flight Snapshot</h2>
          </div>
          <div className="space-y-2 text-sm text-slate-800">
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
            <BatteryMedium className="h-4 w-4 text-blue-700" />
            <h2 className="font-[var(--font-heading)] text-lg text-slate-900">Charging Cost Meaning</h2>
          </div>
          <div className="space-y-2 text-sm text-slate-800">
            <p>
              Session total:{" "}
              <span className="font-semibold">
                ${sessionCost}
              </span>
            </p>
            <p>
              Energy amount:{" "}
              <span className="font-semibold">{chargingEstimate?.energyKwh ?? 52} kWh</span>
            </p>
            <p>
              Unit electricity rate:{" "}
              <span className="font-semibold">
                ${unitRate} per kWh
              </span>
            </p>
            <p className="text-xs text-muted">
              This estimate is for one recommended charging session, not monthly total.
            </p>
          </div>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.08fr_0.92fr]">
        <Card
          className={`transition-opacity duration-200 ${trendBusy ? "opacity-80" : "opacity-100"}`}
          aria-busy={trendBusy}
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <h2 className="font-[var(--font-heading)] text-lg text-slate-900">
              SOH History ({TREND_WINDOWS.find((item) => item.value === trendWindow)?.label ?? "90d"})
            </h2>
            <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1">
              {TREND_WINDOWS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setTrendWindow(item.value)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition duration-200 ${
                    trendWindow === item.value
                      ? "bg-blue-600 text-white shadow-sm"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div className="mb-3 flex items-center justify-between gap-3">
            <p className="text-xs text-muted">
              Solid line = observed latent SOH history. Dashed line = projected SOH forecast.
            </p>
            <span className="text-[11px] text-slate-500">
              {trendBusy ? "Updating view..." : " "}
            </span>
          </div>
          <SohLineChart
            points={trendQuery.data.points}
            forecastPoints={forecastPoints}
            window={trendWindow}
          />
        </Card>
        <Card className="self-start">
          <h2 className="mb-1 font-[var(--font-heading)] text-lg text-slate-900">
            Range & Endurance Forecast
          </h2>
          <p className="mb-3 text-xs text-muted">
            Estimated mission range/endurance sensitivity across charge levels.
          </p>
          <RangeEnduranceChart sohCurrent={health.sohCurrent} />
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.45fr_0.55fr]">
        <Card
          className={`space-y-4 transition-opacity duration-200 ${recommendationBusy ? "opacity-80" : "opacity-100"}`}
          aria-busy={recommendationBusy}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-blue-700" />
              <h2 className="font-[var(--font-heading)] text-lg text-slate-900">
                Flight Recommendations
              </h2>
            </div>
            <label className="text-sm text-muted">
              Month{" "}
              <select
                value={month}
                onChange={(event) => setMonth(event.target.value)}
                className="ml-2 rounded-lg border border-stone-300 bg-white px-2 py-1 text-slate-900 transition duration-200 hover:border-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
              >
                {options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
            <span>Recommendations refresh in place when you change month.</span>
            <span>{recommendationBusy ? "Updating..." : " "}</span>
          </div>

          <RecommendationCalendar
            days={recommendationDays}
            breakdownByDate={recommendations.scoreBreakdownByDate}
            chargePlan={recommendations.chargePlan}
            selectedDate={selectedRecommendationDate}
            onSelectedDateChange={setSelectedRecommendationDate}
          />
        </Card>

        <Card className="self-start space-y-4">
          <h3 className="font-[var(--font-heading)] text-lg text-slate-900">
            Recommendation Highlights
          </h3>
          {nextBestDay ? (
            <div className="rounded-2xl border border-blue-100 bg-blue-50/70 p-3 text-sm">
              <p className="text-muted">Best next day</p>
              <p className="font-semibold text-slate-900">{nextBestDay.date}</p>
              <p className="text-blue-700">Score {nextBestDay.score.toFixed(1)}</p>
            </div>
          ) : selectedRecommendationDate ? (
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm">
              <p className="text-muted">Best next day</p>
              <p className="font-semibold text-slate-900">No later dates this month</p>
              <p className="text-slate-600">You are already viewing one of the final available days.</p>
            </div>
          ) : null}
          <div className="space-y-2">
            {recommendations.cards.map((card) => (
              <div key={card.id} className="rounded-xl border border-stone-200 bg-white/85 p-3 text-sm">
                <p className="font-semibold text-slate-900">{card.action}</p>
                <p className="text-xs text-muted">Confidence {card.confidence.toFixed(2)}</p>
                <ul className="mt-2 space-y-1 text-xs text-slate-700">
                  {card.why.slice(0, 2).map((line) => (
                    <li key={line}>- {line}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.08fr_0.92fr]">
        <Card className="space-y-4">
          <h2 className="font-[var(--font-heading)] text-lg text-slate-900">Route Context</h2>
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
        </Card>
        <Card
          className={`self-start space-y-3 transition-opacity duration-200 ${weatherBusy ? "opacity-80" : "opacity-100"}`}
          aria-busy={weatherBusy}
        >
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-blue-700" />
            <h2 className="font-[var(--font-heading)] text-lg text-slate-900">Weather + Cost Signal</h2>
          </div>
          {weatherQuery.data?.demoMode ? (
            <div className="rounded-lg border border-amber-300 bg-amber-100 px-3 py-2 text-xs text-amber-700">
              Extended forecast estimation active. Recommendations remain available.
            </div>
          ) : null}
          <p className="text-sm text-muted">
            Source mode:{" "}
            <span className="font-semibold capitalize">
              Weather {weatherQuery.data?.mode}
              {chargingEstimate ? ` | Cost ${chargingEstimate.sourceMode}` : ""}
            </span>
          </p>
          <p className="text-[11px] text-slate-500">
            {weatherBusy ? "Refreshing forecast and charging estimate..." : " "}
          </p>
          <div className="space-y-2">
            {weatherQuery.data?.days.slice(0, 5).map((day) => (
              <div
                key={day.date}
                className="flex items-center justify-between rounded-lg border border-stone-200 px-3 py-2 text-xs text-slate-800"
              >
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
          <p className="text-xs text-muted">
            Estimated charging session: $
            {sessionCost} for{" "}
            {chargingEstimate?.energyKwh ?? 52} kWh.
          </p>
        </Card>
      </section>

      <GlossarySection
        title="Dashboard Glossary"
        subtitle="Key metrics used on this page."
        items={glossaryItems}
      />
    </main>
  );
}
