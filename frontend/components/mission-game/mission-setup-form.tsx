"use client";

import { useEffect, useState } from "react";

import { MissionGameBaseline, MissionGameInput, PlaneSummary } from "@/lib/contracts/schemas";

type Props = {
  planes: PlaneSummary[];
  baseline: MissionGameBaseline;
  values: MissionGameInput;
  onChange: (next: MissionGameInput) => void;
  onSubmit: () => void;
  onReset: () => void;
  loading: boolean;
};

export function MissionSetupForm({
  planes,
  baseline,
  values,
  onChange,
  onSubmit,
  onReset,
  loading
}: Props) {
  const selectedSet = new Set(values.planeIds);
  const [durationText, setDurationText] = useState(String(values.plannedDurationMin));
  const [distanceText, setDistanceText] = useState(String(values.routeDistanceKm));
  const [socText, setSocText] = useState(String(values.targetSoc));

  useEffect(() => {
    setDurationText(String(values.plannedDurationMin));
    setDistanceText(String(values.routeDistanceKm));
    setSocText(String(values.targetSoc));
  }, [values.plannedDurationMin, values.routeDistanceKm, values.targetSoc]);

  const parsedDuration =
    durationText.trim() === "" ? Number.NaN : Number.parseFloat(durationText);
  const parsedDistance =
    distanceText.trim() === "" ? Number.NaN : Number.parseFloat(distanceText);
  const parsedSoc = socText.trim() === "" ? Number.NaN : Number.parseFloat(socText);

  const durationError =
    !Number.isFinite(parsedDuration) || parsedDuration < 10 || parsedDuration > 300
      ? "Use 10 to 300 minutes."
      : "";
  const distanceError =
    !Number.isFinite(parsedDistance) || parsedDistance < 10 || parsedDistance > 500
      ? "Use 10 to 500 km."
      : "";
  const socError =
    !Number.isFinite(parsedSoc) || parsedSoc < 50 || parsedSoc > 100
      ? "Use 50% to 100%."
      : "";
  const dateError = values.date ? "" : "Select a mission date.";
  const planeError = values.planeIds.length === 0 ? "Select at least one plane." : "";
  const weatherError =
    values.weatherMode === "manual" &&
    values.manualWeather &&
    (values.manualWeather.windKph < 0 ||
      values.manualWeather.precipMm < 0 ||
      values.manualWeather.tempC < -50 ||
      values.manualWeather.tempC > 60)
      ? "Check manual weather values."
      : "";
  const hasErrors = Boolean(
    durationError || distanceError || socError || dateError || planeError || weatherError
  );

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-sm text-slate-700">
          Mode
          <select
            value={values.mode}
            onChange={(event) =>
              onChange({
                ...values,
                mode: event.target.value as MissionGameInput["mode"],
                planeIds:
                  event.target.value === "single"
                    ? [values.planeIds[0] ?? planes[0]?.planeId ?? ""]
                    : values.planeIds.length
                      ? values.planeIds
                      : [planes[0]?.planeId ?? ""]
              })
            }
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2"
          >
            <option value="single">Detailed (Single Plane)</option>
            <option value="fleet_compare">Compare Fleet</option>
          </select>
        </label>
        <label className="text-sm text-slate-700">
          Flight Date
          <input
            type="date"
            value={values.date}
            onChange={(event) => onChange({ ...values, date: event.target.value })}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2"
          />
          {dateError ? <p className="mt-1 text-xs text-rose-600">{dateError}</p> : null}
        </label>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-3">
        <p className="mb-2 text-sm font-medium text-slate-800">
          {values.mode === "single" ? "Select Plane" : "Select Fleet"}
        </p>
        <div className="grid gap-2 md:grid-cols-2">
          {planes.map((plane) => (
            <label
              key={plane.planeId}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700"
            >
              <input
                type={values.mode === "single" ? "radio" : "checkbox"}
                checked={selectedSet.has(plane.planeId)}
                onChange={() => {
                  if (values.mode === "single") {
                    onChange({ ...values, planeIds: [plane.planeId] });
                    return;
                  }
                  const next = selectedSet.has(plane.planeId)
                    ? values.planeIds.filter((id) => id !== plane.planeId)
                    : [...values.planeIds, plane.planeId];
                  onChange({ ...values, planeIds: next.length ? next : values.planeIds });
                }}
              />
              Plane {plane.planeId} | {plane.registration}
            </label>
          ))}
        </div>
      </div>
      {planeError ? <p className="text-xs text-rose-600">{planeError}</p> : null}

      <div className="grid gap-3 md:grid-cols-3">
        <label className="text-sm text-slate-700">
          Planned Duration (min)
          <input
            type="number"
            min={10}
            max={300}
            value={durationText}
            onChange={(event) => {
              const nextText = event.target.value;
              setDurationText(nextText);
              if (nextText.trim() === "") return;
              const parsed = Number.parseFloat(nextText);
              if (!Number.isFinite(parsed)) return;
              onChange({
                ...values,
                plannedDurationMin: parsed
              });
            }}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2"
          />
          {durationError ? (
            <p className="mt-1 text-xs text-rose-600">{durationError}</p>
          ) : null}
        </label>
        <label className="text-sm text-slate-700">
          Route Distance (km)
          <input
            type="number"
            min={10}
            max={500}
            value={distanceText}
            onChange={(event) => {
              const nextText = event.target.value;
              setDistanceText(nextText);
              if (nextText.trim() === "") return;
              const parsed = Number.parseFloat(nextText);
              if (!Number.isFinite(parsed)) return;
              onChange({
                ...values,
                routeDistanceKm: parsed
              });
            }}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2"
          />
          {distanceError ? (
            <p className="mt-1 text-xs text-rose-600">{distanceError}</p>
          ) : null}
        </label>
        <label className="text-sm text-slate-700">
          Target Charge SOC (%)
          <input
            type="number"
            min={50}
            max={100}
            value={socText}
            onChange={(event) => {
              const nextText = event.target.value;
              setSocText(nextText);
              if (nextText.trim() === "") return;
              const parsed = Number.parseFloat(nextText);
              if (!Number.isFinite(parsed)) return;
              onChange({
                ...values,
                targetSoc: parsed
              });
            }}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2"
          />
          {socError ? <p className="mt-1 text-xs text-rose-600">{socError}</p> : null}
        </label>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <label className="text-sm text-slate-700">
          Payload
          <select
            value={values.payloadLevel}
            onChange={(event) =>
              onChange({
                ...values,
                payloadLevel: event.target.value as MissionGameInput["payloadLevel"]
              })
            }
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2"
          >
            <option value="light">Light</option>
            <option value="medium">Medium</option>
            <option value="heavy">Heavy</option>
          </select>
        </label>
        <label className="text-sm text-slate-700">
          Weather Profile
          <select
            value={values.weatherMode}
            onChange={(event) =>
              onChange({
                ...values,
                weatherMode: event.target.value as MissionGameInput["weatherMode"],
                manualWeather:
                  event.target.value === "manual"
                    ? values.manualWeather ?? baseline.defaults.manualWeather
                    : undefined
              })
            }
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2"
          >
            <option value="forecast">Use Forecast</option>
            <option value="manual">Manual Weather</option>
          </select>
        </label>
      </div>

      {values.weatherMode === "manual" && values.manualWeather ? (
        <div className="grid gap-3 rounded-xl border border-slate-200 bg-white p-3 md:grid-cols-3">
          <label className="text-sm text-slate-700">
            Temperature (C)
            <input
              type="number"
              value={values.manualWeather.tempC}
              onChange={(event) =>
                onChange({
                  ...values,
                  manualWeather: {
                    ...values.manualWeather!,
                    tempC: Number(event.target.value)
                  }
                })
              }
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2"
            />
          </label>
          <label className="text-sm text-slate-700">
            Wind (kph)
            <input
              type="number"
              value={values.manualWeather.windKph}
              onChange={(event) =>
                onChange({
                  ...values,
                  manualWeather: {
                    ...values.manualWeather!,
                    windKph: Number(event.target.value)
                  }
                })
              }
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2"
            />
          </label>
          <label className="text-sm text-slate-700">
            Precipitation (mm)
            <input
              type="number"
              value={values.manualWeather.precipMm}
              onChange={(event) =>
                onChange({
                  ...values,
                  manualWeather: {
                    ...values.manualWeather!,
                    precipMm: Number(event.target.value)
                  }
                })
              }
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2"
            />
          </label>
        </div>
      ) : null}
      {weatherError ? <p className="text-xs text-rose-600">{weatherError}</p> : null}

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onSubmit}
          disabled={loading || hasErrors}
          className="rounded-full bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:opacity-60"
        >
          {loading ? "Running..." : "Run FlightLab"}
        </button>
        <button
          type="button"
          onClick={onReset}
          className="rounded-full border border-slate-300 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
        >
          Reset
        </button>
      </div>
    </div>
  );
}
