from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(parsed):
        return float(default)
    return parsed


def _parse_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    txt = str(value).strip()
    if txt == "" or txt.lower() in {"nan", "nat", "none"}:
        return None
    try:
        return int(round(float(txt)))
    except ValueError:
        return None


def _risk_band(soh: float) -> str:
    if soh >= 80:
        return "low"
    if soh >= 40:
        return "medium"
    if soh >= 20:
        return "watch"
    return "critical"


def _health_label(soh: float) -> tuple[str, str]:
    if soh >= 80:
        return "healthy", "Battery condition is healthy with low degradation signals."
    if soh >= 40:
        return (
            "medium",
            "Battery condition is in the medium band; monitor stress and charging behavior.",
        )
    if soh >= 20:
        return "watch", "Battery condition is in the watch band; reduce stress and plan maintenance."
    return "critical", "Battery condition is degraded; plan maintenance or replacement."


def _load_manifest(repo_root: Path, plane_id: str) -> pd.DataFrame:
    manifest_path = repo_root / "data" / "event_manifest.parquet"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest parquet: {manifest_path}")
    manifest = pd.read_parquet(manifest_path)
    manifest["plane_id"] = manifest["plane_id"].astype(str)
    manifest["event_datetime"] = pd.to_datetime(manifest["event_datetime"], errors="coerce", utc=True)
    manifest["event_date"] = pd.to_datetime(manifest["event_date"], errors="coerce", utc=True)
    return manifest.loc[manifest["plane_id"].eq(str(plane_id))].copy().sort_values("event_datetime")


def _load_latent(repo_root: Path, plane_id: str) -> pd.DataFrame:
    latent_path = (
        repo_root
        / "ml_workspace"
        / "latent_soh"
        / "output"
        / f"plane_{plane_id}"
        / "latent_soh_event_table.csv"
    )
    if not latent_path.exists():
        raise FileNotFoundError(f"Missing latent SOH table: {latent_path}")
    latent = pd.read_csv(latent_path, parse_dates=["event_datetime"])
    latent["plane_id"] = latent["plane_id"].astype(str)
    latent["event_datetime"] = pd.to_datetime(latent["event_datetime"], errors="coerce", utc=True)
    return latent.loc[latent["plane_id"].eq(str(plane_id))].copy().sort_values("event_datetime")


def _window_delta(df: pd.DataFrame, days: int) -> float:
    if df.empty:
        return 0.0
    latest = df["event_datetime"].max()
    if pd.isna(latest):
        return 0.0
    window = df.loc[df["event_datetime"] >= latest - pd.Timedelta(days=days)]
    if len(window) < 2:
        return 0.0
    return float(window["latent_soh_filter_pct"].iloc[-1] - window["latent_soh_filter_pct"].iloc[0])


def _trend_points(df: pd.DataFrame, soh_col: str) -> list[dict[str, Any]]:
    working = df.copy()
    working["date"] = working["event_datetime"].dt.date
    grouped = working.groupby("date", as_index=False)[soh_col].median()
    return [
        {"date": row["date"].isoformat(), "soh": float(row[soh_col]), "source": "blend"}
        for _, row in grouped.iterrows()
    ]


def _latest_charge_soc(df: pd.DataFrame, latest_row: pd.Series) -> float:
    charge_df = df.loc[df["event_type"].astype(str).str.lower().str.contains("charge", na=False)]
    if not charge_df.empty:
        charge_row = charge_df.sort_values("event_datetime").iloc[-1]
        for col in ("soc_max_pct", "soc_mean_pct", "soc_min_pct"):
            if col in charge_row.index:
                val = _safe_float(charge_row.get(col, np.nan), np.nan)
                if math.isfinite(val):
                    return float(np.clip(val, 0.0, 100.0))

    for col in ("soc_mean_pct", "soc_max_pct", "soc_min_pct"):
        if col in latest_row.index:
            val = _safe_float(latest_row.get(col, np.nan), np.nan)
            if math.isfinite(val):
                return float(np.clip(val, 0.0, 100.0))
    return 0.0


def _recent_flight_decay_per_flight(df: pd.DataFrame) -> float:
    flights = df.loc[df["event_type"].eq("flight")].sort_values("event_datetime").copy()
    if flights.empty:
        return -0.02
    flights["next_soh"] = flights["latent_soh_filter_pct"].shift(-1)
    flights["delta"] = flights["next_soh"] - flights["latent_soh_filter_pct"]
    recent = flights.dropna(subset=["delta"]).tail(30)
    if recent.empty:
        return -0.02
    deltas = pd.to_numeric(recent["delta"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if deltas.empty:
        return -0.02
    negative = deltas.loc[deltas < 0]
    candidate = float(np.nanmedian(negative if len(negative) >= 3 else deltas))
    return candidate if candidate < 0 else -0.02


def _load_best_models(forecast_root: Path) -> dict[str, dict[str, Any]]:
    best_path = forecast_root / "best_models_by_horizon.json"
    if not best_path.exists():
        return {}
    try:
        payload = json.loads(best_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def _estimate_model_per_flight(repo_root: Path, plane_id: str) -> tuple[float | None, float]:
    forecast_root = (
        repo_root / "ml_workspace" / "soh_forecast" / "output" / "multihorizon_runner_plane_166"
    )
    best_models = _load_best_models(forecast_root)
    if not best_models:
        return None, 0.55

    estimates: list[tuple[float, float]] = []
    for horizon in (1, 5, 10, 15, 20):
        target_name = f"latent_flight_{horizon}"
        best = best_models.get(target_name)
        if not best:
            continue
        model_col = str(best.get("model", "")).strip()
        if not model_col:
            continue

        pred_path = forecast_root / target_name / f"{target_name}_predictions.csv"
        if not pred_path.exists():
            continue

        pred_df = pd.read_csv(pred_path, parse_dates=["event_datetime"])
        if model_col not in pred_df.columns or "plane_id" not in pred_df.columns:
            continue

        pred_df["plane_id"] = pred_df["plane_id"].astype(str)
        pred_df["event_datetime"] = pd.to_datetime(pred_df["event_datetime"], errors="coerce", utc=True)
        plane_df = pred_df.loc[
            pred_df["plane_id"].eq(str(plane_id))
            & pred_df[model_col].notna()
            & pred_df["latent_soh_filter_pct"].notna()
        ].copy()
        if plane_df.empty:
            continue

        selected = plane_df
        if "split" in plane_df.columns:
            for split_name in ("holdout", "test", "valid", "train"):
                split_df = plane_df.loc[plane_df["split"].eq(split_name)].copy()
                if len(split_df) >= 5:
                    selected = split_df
                    break

        selected = selected.sort_values("event_datetime").tail(40)
        delta = pd.to_numeric(selected[model_col], errors="coerce") - pd.to_numeric(
            selected["latent_soh_filter_pct"], errors="coerce"
        )
        per_flight = (delta / float(horizon)).replace([np.inf, -np.inf], np.nan).dropna()
        if per_flight.empty:
            continue

        negative = per_flight.loc[per_flight < 0]
        estimate = float(np.nanmedian(negative if len(negative) >= 3 else per_flight))
        if estimate >= 0:
            continue

        metrics = best.get("metrics", {})
        delta_mae = _safe_float(metrics.get("delta_mae", np.nan) if isinstance(metrics, dict) else np.nan, np.nan)
        weight = float(1.0 / delta_mae) if math.isfinite(delta_mae) and delta_mae > 0 else 1.0
        estimates.append((estimate, weight))

    if not estimates:
        return None, 0.55

    values = np.array([item[0] for item in estimates], dtype=float)
    weights = np.array([item[1] for item in estimates], dtype=float)
    return float(np.average(values, weights=weights)), float(min(0.92, 0.64 + 0.06 * len(estimates)))


def _estimate_flights_per_day(manifest_df: pd.DataFrame) -> tuple[float, float]:
    flights = manifest_df.loc[manifest_df["is_flight_event"] == 1].copy().sort_values("event_datetime")
    if flights.empty:
        return 0.2, 0.55

    end_ts = flights["event_datetime"].max()
    window = flights.loc[flights["event_datetime"] >= end_ts - pd.Timedelta(days=90)].copy()
    if len(window) < 5:
        window = flights.tail(10).copy()
    if len(window) < 2:
        return 0.2, 0.55

    span_days = (window["event_datetime"].iloc[-1] - window["event_datetime"].iloc[0]).total_seconds() / 86_400.0
    span_days = max(1.0, span_days)
    flights_per_day = float(np.clip(len(window) / span_days, 0.02, 10.0))
    confidence = float(min(0.9, 0.56 + 0.025 * len(window)))
    return flights_per_day, confidence


def _build_last_flight(manifest_df: pd.DataFrame, latent_df: pd.DataFrame) -> dict[str, Any]:
    flights = manifest_df.loc[manifest_df["is_flight_event"] == 1].copy().sort_values("event_datetime")
    if not flights.empty:
        row = flights.iloc[-1]
        return {
            "flightId": int(row["flight_id"]) if pd.notna(row.get("flight_id")) else 0,
            "eventDate": row["event_date"].date().isoformat()
            if pd.notna(row.get("event_date"))
            else row["event_datetime"].date().isoformat(),
            "route": str(row["route"]) if pd.notna(row.get("route")) else "Unknown route",
            "departureAirport": str(row["departure_airport"]) if pd.notna(row.get("departure_airport")) else None,
            "destinationAirport": str(row["destination_airport"])
            if pd.notna(row.get("destination_airport"))
            else None,
            "durationMin": _parse_optional_int(row.get("detail_duration")),
            "eventType": str(row.get("event_type_main")) if pd.notna(row.get("event_type_main")) else "flight",
        }

    latest = latent_df.sort_values("event_datetime").iloc[-1]
    return {
        "flightId": int(_safe_float(latest.get("flight_id"), 0)),
        "eventDate": latest["event_datetime"].date().isoformat(),
        "route": "Unknown route",
        "departureAirport": None,
        "destinationAirport": None,
        "durationMin": _parse_optional_int(_safe_float(latest.get("event_duration_s"), np.nan) / 60.0),
        "eventType": str(latest.get("event_type", "unknown")),
    }


def _build_flights(manifest_df: pd.DataFrame) -> list[dict[str, Any]]:
    if manifest_df.empty:
        return []
    ordered = manifest_df.sort_values("event_datetime", ascending=False).head(160)
    flights = []
    for row in ordered.itertuples(index=False):
        flights.append(
            {
                "flightId": int(row.flight_id) if pd.notna(row.flight_id) else 0,
                "eventDate": row.event_date.date().isoformat()
                if pd.notna(row.event_date)
                else row.event_datetime.date().isoformat(),
                "eventType": str(row.event_type_main) if pd.notna(row.event_type_main) else "unknown",
                "route": str(row.route) if pd.notna(row.route) else None,
                "departureAirport": str(row.departure_airport) if pd.notna(row.departure_airport) else None,
                "destinationAirport": str(row.destination_airport) if pd.notna(row.destination_airport) else None,
                "durationMin": _parse_optional_int(row.detail_duration),
                "isChargingEvent": bool(row.is_charging_event == 1),
                "isFlightEvent": bool(row.is_flight_event == 1),
            }
        )
    return flights


def _build_payload(plane_id: str) -> dict[str, Any]:
    repo_root = _repo_root()
    manifest_df = _load_manifest(repo_root, plane_id)
    latent_df = _load_latent(repo_root, plane_id)
    if manifest_df.empty and latent_df.empty:
        raise RuntimeError(f"No data found for plane {plane_id}")

    latest = latent_df.sort_values("event_datetime").iloc[-1]
    current_soh = _safe_float(latest.get("latent_soh_filter_pct", np.nan), 0.0)
    observed_soh = _safe_float(latest.get("observed_soh_pct", np.nan), current_soh)
    current_charge_soc = _latest_charge_soc(latent_df, latest)
    trend_30 = _window_delta(latent_df, 30)
    trend_90 = _window_delta(latent_df, 90)
    risk_band = _risk_band(current_soh)
    health_label, explanation = _health_label(current_soh)
    updated_at = latest["event_datetime"].to_pydatetime().astimezone(timezone.utc).replace(microsecond=0).isoformat()
    last_flight = _build_last_flight(manifest_df, latent_df)

    flight_time = datetime.fromisoformat(f"{last_flight['eventDate']}T00:00:00+00:00")
    time_since_last_flight_hours = max(
        0,
        int(round((datetime.now(timezone.utc) - flight_time).total_seconds() / 3600.0)),
    )

    model_per_flight, model_conf = _estimate_model_per_flight(repo_root, plane_id)
    if model_per_flight is None or model_per_flight >= 0:
        model_per_flight = _recent_flight_decay_per_flight(latent_df)
        model_conf = 0.62
    if model_per_flight >= 0:
        model_per_flight = -0.02
        model_conf = min(model_conf, 0.58)

    flights_per_day, cadence_conf = _estimate_flights_per_day(manifest_df)
    rul_cycles = int(max(0.0, current_soh / abs(model_per_flight)))
    rul_days = int(max(0.0, math.ceil(rul_cycles / max(flights_per_day, 1e-6))))
    prediction_conf = float(np.clip(0.5 * model_conf + 0.5 * cadence_conf, 0.55, 0.95))
    replacement_date = (
        datetime.now(timezone.utc) + timedelta(days=rul_days)
    ).date().isoformat()

    registration = (
        str(manifest_df["registration"].dropna().iloc[0])
        if not manifest_df.empty and manifest_df["registration"].notna().any()
        else f"Plane {plane_id}"
    )
    aircraft_type = (
        str(manifest_df["aircraft_type"].dropna().iloc[0])
        if not manifest_df.empty and manifest_df["aircraft_type"].notna().any()
        else "Unknown aircraft"
    )

    return {
        "planeId": plane_id,
        "metadata": {
            "registration": registration,
            "aircraftType": aircraft_type,
        },
        "health": {
            "planeId": plane_id,
            "updatedAt": updated_at,
            "sohCurrent": float(current_soh),
            "sohTrend30": float(trend_30),
            "sohTrend90": float(trend_90),
            "currentChargeSoc": float(current_charge_soc),
            "timeSinceLastFlightHours": time_since_last_flight_hours,
            "riskBand": risk_band,
            "healthScore": float(current_soh),
            "healthLabel": health_label,
            "healthExplanation": explanation,
            "metricsExplainabilityVersion": "v1",
            "confidence": prediction_conf,
            "pack": {
                "voltage": _safe_float(latest.get("voltage_mean_v", 0.0), 0.0),
                "current": _safe_float(latest.get("current_abs_mean_a", 0.0), 0.0),
                "tempAvg": _safe_float(latest.get("avg_cell_temp_mean_c", 0.0), 0.0),
                "soc": float(current_charge_soc),
            },
            "lastFlight": last_flight,
        },
        "prediction": {
            "planeId": plane_id,
            "forecast": {
                "replacementDatePred": replacement_date,
                "rulDaysPred": rul_days,
                "rulCyclesPred": rul_cycles,
                "confidence": prediction_conf,
            },
            "sohTargetBlend": float(current_soh),
            "sohProxyPoh": _safe_float(latest.get("latent_soh_smooth_pct", observed_soh), observed_soh),
            "sohObservedNorm": float(observed_soh),
        },
        "trend": {
            "planeId": plane_id,
            "points": _trend_points(latent_df, "latent_soh_filter_pct"),
        },
        "history": {
            "planeId": plane_id,
            "points": _trend_points(
                latent_df,
                "latent_soh_smooth_pct" if "latent_soh_smooth_pct" in latent_df.columns else "latent_soh_filter_pct",
            ),
        },
        "flights": {
            "planeId": plane_id,
            "flights": _build_flights(manifest_df),
        },
        "ops": {
            "flightsPerDayRecent": flights_per_day,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit live plane payloads for frontend routes.")
    parser.add_argument("--plane-id", required=True, help="Plane id to load")
    args = parser.parse_args()

    payload = _build_payload(str(args.plane_id))
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
