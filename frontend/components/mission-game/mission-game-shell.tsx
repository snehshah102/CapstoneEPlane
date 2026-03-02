"use client";

import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  evaluateMissionGame,
  getMissionGameBaseline,
  getPlanes
} from "@/lib/adapters/api-client";
import { MissionGameInput, MissionGameResult } from "@/lib/contracts/schemas";
import { MissionCompareTable } from "@/components/mission-game/mission-compare-table";
import {
  LeaderboardEntry,
  MissionLeaderboard
} from "@/components/mission-game/mission-leaderboard";
import { MissionScorePanel } from "@/components/mission-game/mission-score-panel";
import { MissionSetupForm } from "@/components/mission-game/mission-setup-form";
import { Card } from "@/components/ui/card";

function inputKey(input: MissionGameInput) {
  return JSON.stringify(input);
}

export function MissionGameShell() {
  const [result, setResult] = useState<MissionGameResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const cacheRef = useRef<Map<string, MissionGameResult>>(new Map());

  const planesQuery = useQuery({
    queryKey: ["planes"],
    queryFn: getPlanes
  });
  const baselineQuery = useQuery({
    queryKey: ["mission-game-baseline"],
    queryFn: getMissionGameBaseline
  });

  const planes = useMemo(() => planesQuery.data?.planes ?? [], [planesQuery.data?.planes]);
  const baseline = baselineQuery.data?.baseline;

  const defaultValues = useMemo(() => {
    if (!baseline) return null;
    const defaultPlane = planes[0]?.planeId ?? "166";
    return {
      mode: "single" as const,
      planeIds: [defaultPlane],
      date: baseline.defaults.date,
      plannedDurationMin: baseline.defaults.plannedDurationMin,
      routeDistanceKm: baseline.defaults.routeDistanceKm,
      targetSoc: baseline.defaults.targetSoc,
      payloadLevel: baseline.defaults.payloadLevel,
      weatherMode: baseline.defaults.weatherMode,
      manualWeather: baseline.defaults.manualWeather
    };
  }, [baseline, planes]);

  const [values, setValues] = useState<MissionGameInput | null>(null);
  const hydratedValues = values ?? defaultValues;

  const evaluateMutation = useMutation({
    mutationFn: (input: MissionGameInput) => evaluateMissionGame(input),
    onSuccess: (payload) => {
      setResult(payload.result);
      setError(null);
      if (hydratedValues) {
        cacheRef.current.set(inputKey(hydratedValues), payload.result);
      }
    },
    onError: (err: Error) => {
      setError(err.message);
    }
  });

  if (planesQuery.isLoading || baselineQuery.isLoading || !hydratedValues || !baseline) {
    return <div className="text-sm text-muted">Loading FlightLab...</div>;
  }
  if (planesQuery.isError || baselineQuery.isError || !planesQuery.data) {
    return <div className="text-sm text-rose-600">FlightLab data unavailable.</div>;
  }

  const onEvaluate = async () => {
    if (hydratedValues.planeIds.length === 0) {
      setError("Select at least one plane before evaluation.");
      return;
    }
    const key = inputKey(hydratedValues);
    const cached = cacheRef.current.get(key);
    if (cached) {
      setResult(cached);
      setError(null);
      return;
    }
    await evaluateMutation.mutateAsync(hydratedValues);
  };

  const saveRun = () => {
    if (!result) return;
    const label =
      hydratedValues.mode === "single"
        ? `Plane ${hydratedValues.planeIds[0]}`
        : `${hydratedValues.planeIds.length} planes`;
    const entry: LeaderboardEntry = {
      id: crypto.randomUUID(),
      missionName: `FlightLab Run ${leaderboard.length + 1}`,
      mode: hydratedValues.mode,
      planeLabel: label,
      score: result.overallScore,
      status: result.status,
      timestamp: new Date().toISOString(),
      input: hydratedValues,
      result
    };
    setLeaderboard((prev) =>
      [entry, ...prev].sort((a, b) => b.score - a.score).slice(0, 10)
    );
  };

  const resetMission = () => {
    if (!defaultValues) return;
    setValues(defaultValues);
    setResult(null);
    setError(null);
  };

  return (
    <main className="space-y-6">
      <section className="space-y-2">
        <h1 className="section-title text-slate-900">FlightLab</h1>
        <p className="text-sm text-slate-600">
          Build a mission profile and see how strategy choices impact battery health,
          confidence, and charging cost.
        </p>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <Card>
          <MissionSetupForm
            planes={planes}
            baseline={baseline}
            values={hydratedValues}
            onChange={setValues}
            onSubmit={onEvaluate}
            onReset={resetMission}
            loading={evaluateMutation.isPending}
          />
          {error ? <p className="mt-3 text-sm text-rose-600">{error}</p> : null}
        </Card>

        <div className="space-y-4">
          {result ? (
            <Card>
              <MissionScorePanel result={result} />
              <div className="mt-4 flex items-center gap-2">
                <button
                  type="button"
                  onClick={saveRun}
                  className="rounded-full bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
                >
                  Save Run
                </button>
                <p className="text-xs text-slate-500">Saves to current browser session.</p>
              </div>
            </Card>
          ) : (
            <Card>
              <p className="text-sm text-slate-600">
                Evaluate a mission to view the composite score and recommendations.
              </p>
            </Card>
          )}
          <MissionLeaderboard entries={leaderboard} onClear={() => setLeaderboard([])} />
        </div>
      </section>

      {hydratedValues.mode === "fleet_compare" && result?.perPlaneResults?.length ? (
        <section>
          <h2 className="mb-2 font-[var(--font-heading)] text-2xl text-slate-900">
            Fleet Comparison
          </h2>
          <MissionCompareTable rows={result.perPlaneResults} />
        </section>
      ) : null}
    </main>
  );
}
