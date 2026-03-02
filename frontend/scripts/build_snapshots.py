from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


@dataclass
class LatestTelemetry:
    event_datetime: datetime
    time_ms: float
    pack_voltage: float
    pack_current: float
    pack_temp_avg: float
    pack_soc: float


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_airport_code(label: Any) -> str | None:
    if label is None or (isinstance(label, float) and math.isnan(label)):
        return None
    txt = str(label).strip()
    if len(txt) < 4:
        return None
    return txt[:4].upper()


def risk_band(soh_value: float) -> str:
    if soh_value >= 75:
        return "low"
    if soh_value >= 55:
        return "medium"
    return "high"


def health_label_from_score(score: float) -> str:
    if score >= 75:
        return "healthy"
    if score >= 55:
        return "watch"
    return "critical"


def health_explanation(score: float) -> str:
    if score >= 75:
        return "Battery condition looks healthy for typical training operations."
    if score >= 55:
        return "Battery condition is usable, but wear signals should be monitored closely."
    return "Battery condition is in a critical zone; reduce stress and plan replacement soon."


def parse_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    txt = str(value).strip()
    if txt == "" or txt.lower() in {"none", "nan", "nat"}:
        return None
    try:
        return int(float(txt))
    except ValueError:
        return None


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def build_soh_series(flight_dates: list[date], plane_id: str) -> list[dict[str, Any]]:
    if not flight_dates:
        today = datetime.now(timezone.utc).date()
        return [{"date": today.isoformat(), "soh": 80.0, "source": "blend"}]

    n = len(flight_dates)
    if plane_id == "166":
        start_soh = 88.0
        end_soh = 73.6
    else:
        start_soh = 89.5
        end_soh = 83.9

    series: list[dict[str, Any]] = []
    for i, day in enumerate(flight_dates):
        t = i / max(1, (n - 1))
        base = lerp(start_soh, end_soh, t)
        seasonal = 0.42 * math.sin(i / 5.3)
        soh = max(45.0, min(99.5, base + seasonal))
        source = "blend"
        if i % 7 == 0:
            source = "proxy"
        elif i % 7 == 3:
            source = "observed_norm"
        series.append({"date": day.isoformat(), "soh": round(soh, 3), "source": source})

    return series


def trend_delta(points: list[dict[str, Any]], lookback_days: int) -> float:
    if len(points) < 2:
        return 0.0
    latest = datetime.fromisoformat(points[-1]["date"]).date()
    cutoff = latest - timedelta(days=lookback_days)
    candidates = [
        p for p in points if datetime.fromisoformat(p["date"]).date() <= cutoff
    ]
    old_point = candidates[-1] if candidates else points[0]
    return round(points[-1]["soh"] - old_point["soh"], 3)


def build_predictions(plane_id: str, soh_current: float) -> dict[str, Any]:
    rul_days = max(110, int((soh_current - 45) * 25))
    rul_cycles = int(rul_days * 0.72)
    replacement_date = (
        datetime.now(timezone.utc).date() + timedelta(days=rul_days)
    ).isoformat()
    proxy = round(min(99.0, soh_current + 0.9), 3)
    observed = round(max(0.0, soh_current - 0.8), 3)
    blend = round((0.55 * proxy) + (0.45 * observed), 3)
    confidence = 0.84 if plane_id == "166" else 0.88
    return {
        "planeId": plane_id,
        "forecast": {
            "replacementDatePred": replacement_date,
            "rulDaysPred": rul_days,
            "rulCyclesPred": rul_cycles,
            "confidence": confidence,
        },
        "sohTargetBlend": blend,
        "sohProxyPoh": proxy,
        "sohObservedNorm": observed,
    }


def day_score(
    day: date, plane_soh: float, horizon_days: int, month_anchor: date
) -> dict[str, Any]:
    idx = (day - month_anchor).days
    temp = 17 + 8 * math.sin((idx / 31) * math.pi * 2)
    precip = max(0.0, 3.2 * math.sin((idx / 6) + 0.8))
    wind = 13 + 11 * abs(math.sin(idx / 8))

    temp_penalty = abs(temp - 21) * 1.6
    precip_penalty = precip * 2.9
    wind_penalty = max(0.0, wind - 18) * 1.2
    stress_penalty = max(0.0, (75 - plane_soh) * 0.38)
    charging_penalty = max(0.0, min(12.0, horizon_days * 0.25))
    score = max(
        15.0,
        min(
            99.5,
            90.0
            - temp_penalty
            - precip_penalty
            - wind_penalty
            - stress_penalty
            - charging_penalty,
        ),
    )

    if horizon_days <= 10:
        tier = "high"
    elif horizon_days <= 21:
        tier = "medium"
    else:
        tier = "low"

    if precip > 3.8 or wind > 29:
        summary = "Potential weather wear spike"
    elif temp < 3 or temp > 32:
        summary = "Thermal stress likely"
    else:
        summary = "Battery-friendly flight window"

    return {
        "date": day.isoformat(),
        "score": round(score, 2),
        "confidenceTier": tier,
        "weatherSummary": summary,
        "_breakdown": {
            "weather": round(max(0.0, 100 - (precip_penalty + wind_penalty) * 2.0), 2),
            "thermal": round(max(0.0, 100 - temp_penalty * 3.0), 2),
            "stress": round(max(0.0, 100 - stress_penalty * 5.0), 2),
            "charging": round(max(0.0, 100 - charging_penalty * 6.0), 2),
        },
    }


def build_recommendations(
    plane_id: str, month_value: str, soh_current: float
) -> dict[str, Any]:
    year, month = [int(x) for x in month_value.split("-")]
    start = date(year, month, 1)
    end = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)

    all_days: list[dict[str, Any]] = []
    day = start
    today = datetime.now(timezone.utc).date()
    while day < end:
        horizon = (day - today).days
        all_days.append(day_score(day, soh_current, horizon, start))
        day += timedelta(days=1)

    ranked = sorted(all_days, key=lambda x: x["score"], reverse=True)
    best_days = ranked[:10]
    calendar_days = sorted(all_days, key=lambda x: x["date"])
    score_breakdown_by_date = {
        day["date"]: day["_breakdown"] for day in calendar_days
    }

    def public_day(day_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "date": day_payload["date"],
            "score": day_payload["score"],
            "confidenceTier": day_payload["confidenceTier"],
            "weatherSummary": day_payload["weatherSummary"],
        }
    charge_plan = []
    for best in best_days[:3]:
        best_date = datetime.fromisoformat(best["date"]).date()
        charge_plan.append(
            {
                "date": best_date.isoformat(),
                "targetSoc": 80,
                "chargeWindowStart": (best_date - timedelta(days=1)).isoformat() + "T18:30:00Z",
                "chargeWindowEnd": (best_date - timedelta(days=1)).isoformat() + "T21:15:00Z",
                "rationale": "Minimize high-SOC idle time while preserving departure buffer.",
            }
        )

    cards = [
        {
            "id": "timing-best-days",
            "type": "timing",
            "action": "Fly on top-scoring days with stable temperature and low wind.",
            "confidence": 0.82,
            "why": [
                "Lower thermal spread expected",
                "Reduced projected climb stress",
                "Weather volatility inside acceptable band",
            ],
        },
        {
            "id": "charge-window",
            "type": "charging",
            "action": "Charge to 80% the evening before departure, not days early.",
            "confidence": 0.88,
            "why": [
                "High SOC storage accelerates degradation",
                "Shorter dwell near high voltage",
                "Health-preserving default for repetitive sorties",
            ],
        },
        {
            "id": "avoid-idle-full",
            "type": "dont",
            "action": "Avoid parking above 95% SOC overnight unless operationally required.",
            "confidence": 0.84,
            "why": [
                "Reduces cumulative calendar wear",
                "Protects cell balancing margin",
                "Improves long-run SOH stability",
            ],
        },
    ]

    return {
        "recommendations": {
            "planeId": plane_id,
            "month": month_value,
            "generatedAt": utc_now_iso(),
            "flightDayScores": [public_day(day) for day in best_days],
            "calendarDays": [public_day(day) for day in calendar_days],
            "scoreBreakdownByDate": score_breakdown_by_date,
            "learnAssumptionsRef": "learn_assumptions_v1",
            "chargePlan": charge_plan,
            "cards": cards,
        }
    }


def glossary_payload() -> dict[str, Any]:
    return {
        "version": "v1",
        "items": [
            {
                "id": "soh",
                "term": "State of Health (SOH)",
                "plainLanguage": "How healthy the battery is compared to when it was new.",
                "whyItMatters": "Lower SOH means reduced flight endurance and faster aging risk.",
                "technicalDetail": "SOH is represented as a percentage relative to nominal new-pack capacity.",
            },
            {
                "id": "trend_points",
                "term": "Trend Points",
                "plainLanguage": "The change in SOH over time, shown in points.",
                "whyItMatters": "Negative values mean battery health is dropping.",
                "technicalDetail": "Trend is computed as current SOH minus SOH at the selected lookback window.",
            },
            {
                "id": "confidence",
                "term": "Confidence",
                "plainLanguage": "How certain the model is about the recommendation.",
                "whyItMatters": "Higher confidence means the suggestion is more reliable.",
                "technicalDetail": "Confidence combines fit quality, agreement between labels, and stability indicators.",
            },
            {
                "id": "rul",
                "term": "Remaining Useful Life (RUL)",
                "plainLanguage": "Estimated time and cycles before battery replacement is recommended.",
                "whyItMatters": "Helps planning maintenance and avoiding last-minute downtime.",
            },
            {
                "id": "risk",
                "term": "Battery Health Meter",
                "plainLanguage": "A student-friendly view of battery condition: Healthy, Watch, or Critical.",
                "whyItMatters": "Shows when to keep normal operations versus reduce stress and plan replacement.",
            },
            {
                "id": "calendar_score",
                "term": "Flight Day Score",
                "plainLanguage": "How favorable each day is for battery-friendly operations.",
                "whyItMatters": "Higher scores generally mean lower expected wear.",
                "technicalDetail": "Score blends weather, thermal stress, battery condition, and charging timing effects.",
            },
            {
                "id": "charge_window",
                "term": "Charge Window",
                "plainLanguage": "Recommended time to charge before a planned flight.",
                "whyItMatters": "Charging too early and leaving high SOC can increase wear.",
            },
        ],
    }


def build_learn_baseline(plane_id: str, health_score: float, rul_days: int) -> dict[str, Any]:
    label = health_label_from_score(health_score)
    return {
        "baseline": {
            "planeId": plane_id,
            "assumptionsVersion": "learn_assumptions_v1",
            "baselineInputs": {
                "ambientTempC": 21,
                "flightDurationMin": 45,
                "expectedPowerKw": 28,
                "windSeverity": 35,
                "precipitationSeverity": 20,
                "chargeTargetSoc": 80,
                "chargeLeadHours": 12,
                "highSocIdleHours": 2,
                "flightsPerWeek": 6,
                "thermalManagementQuality": 78,
                "cellImbalanceSeverity": 22,
                "socEstimatorUncertainty": 18,
            },
            "baselineOutputs": {
                "sohImpactDelta": -0.18,
                "healthScore": round(health_score, 2),
                "healthLabel": label,
                "rulDaysShift": -4,
                "recommendationSummary": f"Moderate mission profile. Current projected RUL is about {rul_days} days.",
            },
        }
    }


def scan_latest_telemetry(timeseries_path: Path) -> dict[str, LatestTelemetry]:
    latest: dict[str, LatestTelemetry] = {}
    parquet_file = pq.ParquetFile(timeseries_path)
    columns = [
        "plane_id",
        "event_datetime",
        "time_ms",
        "pack_voltage",
        "pack_current",
        "pack_temp_avg",
        "pack_soc",
    ]

    for batch in parquet_file.iter_batches(batch_size=200_000, columns=columns):
        frame = batch.to_pandas()
        frame["event_datetime"] = pd.to_datetime(frame["event_datetime"], errors="coerce", utc=True)
        frame["time_ms"] = pd.to_numeric(frame["time_ms"], errors="coerce")
        frame["pack_voltage"] = pd.to_numeric(frame["pack_voltage"], errors="coerce")
        frame["pack_current"] = pd.to_numeric(frame["pack_current"], errors="coerce")
        frame["pack_temp_avg"] = pd.to_numeric(frame["pack_temp_avg"], errors="coerce")
        frame["pack_soc"] = pd.to_numeric(frame["pack_soc"], errors="coerce")
        frame = frame.dropna(
            subset=[
                "plane_id",
                "event_datetime",
                "time_ms",
                "pack_voltage",
                "pack_current",
                "pack_temp_avg",
                "pack_soc",
            ]
        )
        if frame.empty:
            continue
        for plane_id in frame["plane_id"].astype(str).unique():
            sub = frame[frame["plane_id"].astype(str) == plane_id]
            row = sub.sort_values(["event_datetime", "time_ms"]).iloc[-1]
            candidate = LatestTelemetry(
                event_datetime=row["event_datetime"].to_pydatetime(),
                time_ms=float(row["time_ms"]),
                pack_voltage=float(row["pack_voltage"]),
                pack_current=float(row["pack_current"]),
                pack_temp_avg=float(row["pack_temp_avg"]),
                pack_soc=float(row["pack_soc"]),
            )
            prev = latest.get(plane_id)
            if not prev:
                latest[plane_id] = candidate
            else:
                newer = (
                    candidate.event_datetime > prev.event_datetime
                    or (
                        candidate.event_datetime == prev.event_datetime
                        and candidate.time_ms > prev.time_ms
                    )
                )
                if newer:
                    latest[plane_id] = candidate
    return latest


def write_json(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_snapshots(data_dir: Path, out_dir: Path):
    manifest_path = data_dir / "event_manifest.parquet"
    timeseries_path = data_dir / "event_timeseries.parquet"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing {manifest_path}")
    if not timeseries_path.exists():
        raise FileNotFoundError(f"Missing {timeseries_path}")

    manifest = pd.read_parquet(manifest_path)
    manifest["event_datetime"] = pd.to_datetime(
        manifest["event_datetime"], errors="coerce", utc=True
    )
    manifest["event_date"] = pd.to_datetime(
        manifest["event_date"], errors="coerce", utc=True
    )
    manifest["plane_id"] = manifest["plane_id"].astype(str)

    latest_telemetry = scan_latest_telemetry(timeseries_path)

    plane_summaries: list[dict[str, Any]] = []
    planes = sorted(manifest["plane_id"].dropna().unique().tolist())
    month_values = [
        (datetime.now(timezone.utc).date().replace(day=1) + timedelta(days=offset * 31)).strftime("%Y-%m")
        for offset in range(4)
    ]

    for plane_id in planes:
        plane_df = manifest[manifest["plane_id"] == plane_id].copy()
        plane_df = plane_df.sort_values("event_datetime")

        flights_df = plane_df[plane_df["is_flight_event"] == 1].copy()
        flight_dates = [
            ts.date()
            for ts in flights_df["event_date"].dropna().sort_values().dt.tz_convert("UTC")
        ]

        trend_points = build_soh_series(flight_dates, plane_id)
        soh_current = float(trend_points[-1]["soh"])
        soh_trend30 = trend_delta(trend_points, 30)
        soh_trend90 = trend_delta(trend_points, 90)
        prediction = build_predictions(plane_id, soh_current)
        health_score = round(max(0.0, min(100.0, soh_current)), 2)
        health_label = health_label_from_score(health_score)
        health_note = health_explanation(health_score)

        latest = latest_telemetry.get(plane_id)
        if latest:
            pack_voltage = latest.pack_voltage
            pack_current = latest.pack_current
            pack_temp_avg = latest.pack_temp_avg
            pack_soc = latest.pack_soc
            updated_at = latest.event_datetime.replace(microsecond=0).isoformat()
        else:
            pack_voltage = 386.0
            pack_current = 12.0
            pack_temp_avg = 24.0
            pack_soc = 77.0
            updated_at = utc_now_iso()

        if flights_df.empty:
            last_row = plane_df.iloc[-1]
        else:
            last_row = flights_df.iloc[-1]

        last_flight = {
            "flightId": int(last_row["flight_id"]) if pd.notna(last_row["flight_id"]) else 0,
            "eventDate": pd.to_datetime(last_row["event_date"], utc=True).date().isoformat()
            if pd.notna(last_row["event_date"])
            else datetime.now(timezone.utc).date().isoformat(),
            "route": str(last_row["route"]) if pd.notna(last_row["route"]) else "Unknown route",
            "departureAirport": str(last_row["departure_airport"])
            if pd.notna(last_row["departure_airport"])
            else None,
            "destinationAirport": str(last_row["destination_airport"])
            if pd.notna(last_row["destination_airport"])
            else None,
            "durationMin": parse_optional_int(last_row["detail_duration"]),
            "eventType": str(last_row["event_type_main"])
            if pd.notna(last_row["event_type_main"])
            else "unknown",
        }

        health = {
            "planeId": plane_id,
            "updatedAt": updated_at,
            "sohCurrent": round(soh_current, 3),
            "sohTrend30": round(soh_trend30, 3),
            "sohTrend90": round(soh_trend90, 3),
            "riskBand": risk_band(soh_current),
            "healthScore": health_score,
            "healthLabel": health_label,
            "healthExplanation": health_note,
            "metricsExplainabilityVersion": "v1",
            "confidence": prediction["forecast"]["confidence"],
            "pack": {
                "voltage": round(pack_voltage, 2),
                "current": round(pack_current, 2),
                "tempAvg": round(pack_temp_avg, 2),
                "soc": round(pack_soc, 2),
            },
            "lastFlight": last_flight,
        }

        summary = {
            "planeId": plane_id,
            "registration": str(plane_df["registration"].dropna().iloc[0])
            if plane_df["registration"].notna().any()
            else f"Plane {plane_id}",
            "aircraftType": str(plane_df["aircraft_type"].dropna().iloc[0])
            if plane_df["aircraft_type"].notna().any()
            else "Velis Electro",
            "flightsCount": int((plane_df["is_flight_event"] == 1).sum()),
            "chargingEventsCount": int((plane_df["is_charging_event"] == 1).sum()),
            "sohCurrent": round(soh_current, 3),
            "sohTrend30": round(soh_trend30, 3),
            "riskBand": risk_band(soh_current),
            "updatedAt": updated_at,
        }
        plane_summaries.append(summary)

        flights_payload = {
            "planeId": plane_id,
            "flights": [
                {
                    "flightId": int(row.flight_id) if pd.notna(row.flight_id) else 0,
                    "eventDate": row.event_date.date().isoformat()
                    if pd.notna(row.event_date)
                    else datetime.now(timezone.utc).date().isoformat(),
                    "eventType": str(row.event_type_main)
                    if pd.notna(row.event_type_main)
                    else "unknown",
                    "route": str(row.route) if pd.notna(row.route) else None,
                    "departureAirport": str(row.departure_airport)
                    if pd.notna(row.departure_airport)
                    else None,
                    "destinationAirport": str(row.destination_airport)
                    if pd.notna(row.destination_airport)
                    else None,
                    "durationMin": parse_optional_int(row.detail_duration),
                    "isChargingEvent": bool(row.is_charging_event == 1),
                    "isFlightEvent": bool(row.is_flight_event == 1),
                }
                for row in plane_df.sort_values("event_datetime", ascending=False)
                .head(140)
                .itertuples(index=False)
            ],
        }

        telemetry_payload = {
            "planeId": plane_id,
            "updatedAt": updated_at,
            "packVoltage": round(pack_voltage, 2),
            "packCurrent": round(pack_current, 2),
            "packTempAvg": round(pack_temp_avg, 2),
            "packSoc": round(pack_soc, 2),
        }

        write_json(out_dir / f"plane_{plane_id}_kpis.json", {"health": health, "prediction": prediction})
        write_json(out_dir / f"plane_{plane_id}_soh_trend.json", {"planeId": plane_id, "points": trend_points})
        write_json(out_dir / f"plane_{plane_id}_flights.json", flights_payload)
        write_json(out_dir / f"plane_{plane_id}_telemetry_latest.json", telemetry_payload)
        write_json(
            out_dir / f"learn_baseline_plane_{plane_id}.json",
            build_learn_baseline(
                plane_id=plane_id,
                health_score=health_score,
                rul_days=prediction["forecast"]["rulDaysPred"],
            ),
        )

        for month_value in month_values:
            recs = build_recommendations(plane_id, month_value, soh_current)
            write_json(
                out_dir / f"plane_{plane_id}_recommendations_{month_value.replace('-', '_')}.json",
                recs,
            )

    plane_summaries = sorted(plane_summaries, key=lambda x: x["planeId"])
    write_json(out_dir / "planes.json", {"planes": plane_summaries})
    write_json(out_dir / "glossary.json", glossary_payload())


def main():
    parser = argparse.ArgumentParser(description="Build frontend mock snapshots from parquet data.")
    parser.add_argument(
        "--data-dir",
        default="../data",
        help="Directory containing event_manifest.parquet and event_timeseries.parquet",
    )
    parser.add_argument(
        "--out-dir",
        default="public/mock",
        help="Output directory for frontend JSON snapshots",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    frontend_root = script_dir.parent
    data_dir = (frontend_root / args.data_dir).resolve()
    out_dir = (frontend_root / args.out_dir).resolve()

    build_snapshots(data_dir, out_dir)
    print(f"Snapshots generated in {out_dir}")


if __name__ == "__main__":
    main()
