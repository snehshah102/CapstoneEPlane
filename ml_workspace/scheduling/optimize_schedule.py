from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FORECAST_MODELS = PROJECT_ROOT / "ml_workspace" / "soh_forecast" / "output" / "models"
DEFAULT_CIRCUIT_MODEL = PROJECT_ROOT / "ml_workspace" / "circuit_capacity" / "output" / "circuit_model.json"


def _load_degradation_model(models_dir: Path, model_name: str) -> dict[str, Any]:
    return joblib.load(models_dir / f"{model_name}.joblib")


def _load_circuit_model(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _poh_soc_per_circuit(soh_pct: float, soh_grid: list[float], soc_grid: list[float]) -> float:
    return float(np.interp(soh_pct, np.array(soh_grid, dtype=float), np.array(soc_grid, dtype=float)))


def _build_feature_row(
    feature_names: list[str],
    medians: dict[str, float],
    event_type: str,
    delta_days: float,
    soc_span_pct: float,
    delta_ah: float,
    cumulative_ah: float,
    delta_cycles: float,
    cumulative_cycles: float,
    delta_efc: float,
    cumulative_efc: float,
) -> np.ndarray:
    row = {}
    for name in feature_names:
        if name.startswith("event_type_"):
            row[name] = 1.0 if name == f"event_type_{event_type}" else 0.0
        elif name == "delta_days":
            row[name] = delta_days
        elif name == "log1p_delta_days":
            row[name] = float(np.log1p(max(delta_days, 0.0)))
        elif name == "usage_soc_per_day":
            row[name] = soc_span_pct / max(delta_days, 1.0 / 24.0)
        elif name == "delta_ah":
            row[name] = delta_ah
        elif name == "log1p_delta_ah":
            row[name] = float(np.log1p(max(delta_ah, 0.0)))
        elif name == "usage_soc_per_ah":
            row[name] = soc_span_pct / max(delta_ah, 1e-3)
        elif name == "cumulative_ah":
            row[name] = cumulative_ah
        elif name == "delta_cycles":
            row[name] = delta_cycles
        elif name == "log1p_delta_cycles":
            row[name] = float(np.log1p(max(delta_cycles, 0.0)))
        elif name == "usage_soc_per_cycle":
            row[name] = soc_span_pct / max(delta_cycles, 1.0)
        elif name == "cumulative_cycles":
            row[name] = cumulative_cycles
        elif name == "delta_efc":
            row[name] = delta_efc
        elif name == "log1p_delta_efc":
            row[name] = float(np.log1p(max(delta_efc, 0.0)))
        elif name == "usage_soc_per_efc":
            row[name] = soc_span_pct / max(delta_efc, 1e-3)
        elif name == "cumulative_efc":
            row[name] = cumulative_efc
        elif name == "gap_gt_max":
            row[name] = 1.0 if delta_days > 30.0 else 0.0
        elif name == "soc_span_pct":
            row[name] = soc_span_pct
        else:
            row[name] = float(medians.get(name, 0.0))
    return np.array([row[name] for name in feature_names], dtype=float)


def _generate_schedule(strategy: str, total_flights: int, circuits_per_flight: list[int], horizon_days: float, min_turnaround_min: float) -> list[dict[str, Any]]:
    if total_flights <= 0:
        return []
    horizon_min = horizon_days * 1440.0
    if strategy == "cluster":
        starts = [i * min_turnaround_min for i in range(total_flights)]
    elif strategy == "backload":
        starts = [horizon_min - (total_flights - i) * min_turnaround_min for i in range(total_flights)]
    else:
        spacing = max(min_turnaround_min, horizon_min / max(total_flights, 1))
        starts = [i * spacing for i in range(total_flights)]

    schedule = []
    for i, start in enumerate(starts):
        schedule.append({"type": "flight", "start_min": float(start), "duration_min": 30.0, "circuits": int(circuits_per_flight[i])})
    return schedule


def _simulate(
    events: list[dict[str, Any]],
    model_name: str,
    models_dir: Path,
    circuit_model_path: Path,
    plane_id: str,
    initial_soc: float,
    initial_soh: float,
    rated_capacity_ah: float,
    initial_cumulative_ah: float,
    initial_cumulative_cycles: float,
    initial_cumulative_efc: float,
    reserve_soc: float,
    charge_rate_pct_per_min: float,
    min_turnaround_min: float,
) -> dict[str, Any]:
    payload = _load_degradation_model(models_dir, model_name)
    model = payload["model"]
    scaler = payload["scaler"]
    bundle = payload["bundle"]
    feature_names = bundle["feature_names"]
    medians = bundle["feature_medians"]
    target_name = bundle.get("target_name", "delta_soh")

    circuit_meta = _load_circuit_model(circuit_model_path)
    soh_grid = circuit_meta["poh_soh_grid"]
    soc_grid = circuit_meta["poh_circuit_soc"]
    k_plane = circuit_meta.get("k_plane", {}).get(str(plane_id), circuit_meta.get("default_k", 1.0))

    current_soc = initial_soc
    current_soh = initial_soh
    rated_capacity_ah = float(rated_capacity_ah)
    cumulative_ah = float(initial_cumulative_ah)
    cumulative_cycles = float(initial_cumulative_cycles)
    cumulative_efc = float(initial_cumulative_efc)
    last_start = None
    output_events = []
    total_degradation = 0.0
    min_soc = current_soc
    violated_reserve = False

    idx = 0
    for event in sorted(events, key=lambda e: e.get("start_min", 0.0)):
        event_type = event["type"]
        start_min = event.get("start_min", idx * min_turnaround_min)
        duration_min = float(event.get("duration_min", 0.0))
        delta_days = 0.5 / 24.0 if last_start is None else max((start_min - last_start) / 1440.0, 0.5 / 24.0)

        if event_type == "flight":
            circuits = int(event.get("circuits", 1))
            soc_per_circuit = k_plane * _poh_soc_per_circuit(current_soh, soh_grid, soc_grid)
            soc_span = circuits * soc_per_circuit
            soc_end = current_soc - soc_span
            delta_cycles = float(event.get("cycles", event.get("circuits", 1)))
        elif event_type == "charge":
            soc_end = min(100.0, current_soc + charge_rate_pct_per_min * duration_min)
            soc_span = max(0.0, soc_end - current_soc)
            delta_cycles = 0.0
        else:
            soc_span = 0.0
            soc_end = current_soc
            delta_cycles = 0.0

        delta_ah = rated_capacity_ah * abs(soc_span) / 100.0
        cumulative_ah += delta_ah
        cumulative_cycles += delta_cycles
        delta_efc = abs(soc_span) / 100.0
        cumulative_efc += delta_efc
        feature_row = _build_feature_row(
            feature_names,
            medians,
            event_type,
            delta_days,
            soc_span,
            delta_ah,
            cumulative_ah,
            delta_cycles,
            cumulative_cycles,
            delta_efc,
            cumulative_efc,
        )
        pred = float(model.predict(scaler.transform([feature_row]))[0])
        if target_name == "delta_soh_per_day":
            pred_delta = pred * delta_days
        elif target_name == "delta_soh_per_ah":
            pred_delta = pred * delta_ah
        elif target_name == "delta_soh_per_cycle":
            pred_delta = pred * delta_cycles
        elif target_name == "delta_soh_per_efc":
            pred_delta = pred * delta_efc
        elif target_name == "next_soh":
            pred_delta = pred - current_soh
        else:
            pred_delta = pred
        soh_end = current_soh + pred_delta
        total_degradation += pred_delta

        if soc_end < reserve_soc:
            violated_reserve = True
        min_soc = min(min_soc, soc_end)

        output_events.append(
            {
                "event_index": idx,
                "event_type": event_type,
                "start_min": float(start_min),
                "duration_min": float(duration_min),
                "soc_start_pct": float(current_soc),
                "soc_end_pct": float(soc_end),
                "soh_start_pct": float(current_soh),
                "soh_end_pct": float(soh_end),
                "pred_delta_soh": float(pred_delta),
            }
        )

        current_soc = soc_end
        current_soh = soh_end
        last_start = start_min
        idx += 1

        # Add immediate charge if reserve would be violated before next flight.
        if event_type == "flight" and current_soc < reserve_soc + 5.0:
            charge_duration = max(0.0, (100.0 - current_soc) / max(charge_rate_pct_per_min, 0.1))
            charge_start = last_start + min_turnaround_min
            charge_soc_end = min(100.0, current_soc + charge_rate_pct_per_min * charge_duration)
            charge_delta_days = max(min_turnaround_min / 1440.0, 0.5 / 24.0)
            charge_soc_span = max(0.0, charge_soc_end - current_soc)
            charge_delta_ah = rated_capacity_ah * abs(charge_soc_span) / 100.0
            cumulative_ah += charge_delta_ah
            cumulative_cycles += 0.0
            charge_delta_efc = abs(charge_soc_span) / 100.0
            cumulative_efc += charge_delta_efc

            feature_row = _build_feature_row(
                feature_names,
                medians,
                "charge",
                charge_delta_days,
                charge_soc_span,
                charge_delta_ah,
                cumulative_ah,
                0.0,
                cumulative_cycles,
                charge_delta_efc,
                cumulative_efc,
            )
            pred = float(model.predict(scaler.transform([feature_row]))[0])
            if target_name == "delta_soh_per_day":
                pred_delta = pred * charge_delta_days
            elif target_name == "delta_soh_per_ah":
                pred_delta = pred * charge_delta_ah
            elif target_name == "delta_soh_per_cycle":
                pred_delta = 0.0
            elif target_name == "delta_soh_per_efc":
                pred_delta = pred * charge_delta_efc
            elif target_name == "next_soh":
                pred_delta = pred - current_soh
            else:
                pred_delta = pred
            charge_soh_end = current_soh + pred_delta
            total_degradation += pred_delta

            output_events.append(
                {
                    "event_index": idx,
                    "event_type": "charge",
                    "start_min": float(charge_start),
                    "duration_min": float(charge_duration),
                    "soc_start_pct": float(current_soc),
                    "soc_end_pct": float(charge_soc_end),
                    "soh_start_pct": float(current_soh),
                    "soh_end_pct": float(charge_soh_end),
                    "pred_delta_soh": float(pred_delta),
                }
            )

            current_soc = charge_soc_end
            current_soh = charge_soh_end
            last_start = charge_start
            idx += 1

    return {
        "summary": {
            "total_pred_delta_soh": float(total_degradation),
            "min_soc_pct": float(min_soc),
            "reserve_soc_pct": float(reserve_soc),
            "violated_reserve": bool(violated_reserve),
        },
        "events": output_events,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize a fixed-demand schedule using degradation model.")
    parser.add_argument("--plane-id", default="166")
    parser.add_argument("--total-flights", type=int, required=True)
    parser.add_argument("--circuits-per-flight", type=int, default=1)
    parser.add_argument("--horizon-days", type=float, default=7.0)
    parser.add_argument("--initial-soc-pct", type=float, default=100.0)
    parser.add_argument("--initial-soh-pct", type=float, default=95.0)
    parser.add_argument("--rated-capacity-ah", type=float, default=29.0)
    parser.add_argument("--initial-cumulative-ah", type=float, default=0.0)
    parser.add_argument("--initial-cumulative-cycles", type=float, default=0.0)
    parser.add_argument("--initial-cumulative-efc", type=float, default=0.0)
    parser.add_argument("--charge-rate-pct-per-min", type=float, default=1.0)
    parser.add_argument("--min-turnaround-min", type=float, default=30.0)
    parser.add_argument("--reserve-soc-pct", type=float, default=30.0)
    parser.add_argument("--model-name", default="elastic_net")
    parser.add_argument("--models-dir", default=str(DEFAULT_FORECAST_MODELS))
    parser.add_argument("--circuit-model-path", default=str(DEFAULT_CIRCUIT_MODEL))
    parser.add_argument("--output-path", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    circuits_list = [int(args.circuits_per_flight)] * int(args.total_flights)

    strategies = ["even", "cluster", "backload"]
    results = []
    for strat in strategies:
        schedule = _generate_schedule(strat, args.total_flights, circuits_list, args.horizon_days, args.min_turnaround_min)
        sim = _simulate(
            schedule,
            args.model_name,
            Path(args.models_dir),
            Path(args.circuit_model_path),
            str(args.plane_id),
            float(args.initial_soc_pct),
            float(args.initial_soh_pct),
            float(args.rated_capacity_ah),
            float(args.initial_cumulative_ah),
            float(args.initial_cumulative_cycles),
            float(args.initial_cumulative_efc),
            float(args.reserve_soc_pct),
            float(args.charge_rate_pct_per_min),
            float(args.min_turnaround_min),
        )
        results.append({"strategy": strat, "summary": sim["summary"], "events": sim["events"]})

    best = min(results, key=lambda r: r["summary"]["total_pred_delta_soh"])
    output = {"best": best, "all": results}

    out_path = Path(args.output_path) if args.output_path else Path.cwd() / "optimized_schedule.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
