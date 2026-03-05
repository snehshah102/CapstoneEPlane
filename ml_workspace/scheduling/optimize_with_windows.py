from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FORECAST_MODELS = PROJECT_ROOT / "ml_workspace" / "soh_forecast" / "output" / "models"
DEFAULT_CIRCUIT_MODEL = PROJECT_ROOT / "ml_workspace" / "circuit_capacity" / "output" / "circuit_model.json"


@dataclass
class Config:
    windows_path: Path
    model_name: str
    models_dir: Path = DEFAULT_FORECAST_MODELS
    circuit_model_path: Path = DEFAULT_CIRCUIT_MODEL
    reserve_soc_pct: float = 30.0
    min_turnaround_min: float = 30.0
    lookahead: int = 5


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


def _apply_charge_windows(
    soc_start: float,
    soh_start: float,
    cumulative_ah: float,
    cumulative_cycles: float,
    cumulative_efc: float,
    last_time: float,
    target_time: float,
    charge_windows: list[dict[str, Any]],
    charge_rate_default: float,
    reserve_soc_pct: float,
    model_payload: dict[str, Any],
    rated_capacity_ah: float,
) -> tuple[float, float, float, float, float, list[dict[str, Any]]]:
    model = model_payload["model"]
    scaler = model_payload["scaler"]
    bundle = model_payload["bundle"]
    feature_names = bundle["feature_names"]
    medians = bundle["feature_medians"]
    target_name = bundle.get("target_name", "delta_soh")

    current_soc = soc_start
    current_soh = soh_start
    current_cum_ah = cumulative_ah
    current_cum_cycles = cumulative_cycles
    current_cum_efc = cumulative_efc
    last_event_time = last_time
    events = []

    for window in charge_windows:
        start = float(window["start_min"])
        end = float(window["end_min"])
        if end <= last_event_time or start >= target_time:
            continue
        charge_rate = float(window.get("charge_rate_pct_per_min", charge_rate_default))
        charge_start = max(start, last_event_time)
        charge_end = min(end, target_time)
        duration = max(0.0, charge_end - charge_start)
        if duration <= 0.0 or current_soc >= 99.0:
            continue

        delta_days = max((charge_start - last_event_time) / 1440.0, 0.5 / 24.0)
        soc_end = min(100.0, current_soc + charge_rate * duration)
        soc_span = max(0.0, soc_end - current_soc)
        delta_ah = rated_capacity_ah * abs(soc_span) / 100.0
        current_cum_ah += delta_ah
        delta_cycles = 0.0
        current_cum_cycles += delta_cycles
        delta_efc = abs(soc_span) / 100.0
        current_cum_efc += delta_efc
        feature_row = _build_feature_row(
            feature_names,
            medians,
            "charge",
            delta_days,
            soc_span,
            delta_ah,
            current_cum_ah,
            delta_cycles,
            current_cum_cycles,
            delta_efc,
            current_cum_efc,
        )
        pred = float(model.predict(scaler.transform([feature_row]))[0])
        if target_name == "delta_soh_per_day":
            pred_delta = pred * delta_days
        elif target_name == "delta_soh_per_ah":
            pred_delta = pred * delta_ah
        elif target_name == "delta_soh_per_cycle":
            pred_delta = 0.0
        elif target_name == "delta_soh_per_efc":
            pred_delta = pred * delta_efc
        elif target_name == "next_soh":
            pred_delta = pred - current_soh
        else:
            pred_delta = pred
        current_soh = current_soh + pred_delta

        events.append(
            {
                "type": "charge",
                "start_min": charge_start,
                "duration_min": duration,
                "soc_start_pct": current_soc,
                "soc_end_pct": soc_end,
                "soh_start_pct": current_soh - pred_delta,
                "soh_end_pct": current_soh,
                "pred_delta_soh": pred_delta,
            }
        )
        current_soc = soc_end
        last_event_time = charge_end

    if current_soc < reserve_soc_pct:
        return current_soc, current_soh, current_cum_ah, current_cum_cycles, current_cum_efc, last_event_time, events
    return current_soc, current_soh, current_cum_ah, current_cum_cycles, current_cum_efc, last_event_time, events


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Optimize schedule using flight availability and charge windows.")
    parser.add_argument("--windows-path", required=True, help="JSON with flight and charge windows.")
    parser.add_argument("--model-name", default="elastic_net")
    parser.add_argument("--models-dir", default=str(DEFAULT_FORECAST_MODELS))
    parser.add_argument("--circuit-model-path", default=str(DEFAULT_CIRCUIT_MODEL))
    parser.add_argument("--reserve-soc-pct", type=float, default=30.0)
    parser.add_argument("--min-turnaround-min", type=float, default=30.0)
    parser.add_argument("--lookahead", type=int, default=5)
    ns = parser.parse_args()
    return Config(
        windows_path=Path(ns.windows_path),
        model_name=ns.model_name,
        models_dir=Path(ns.models_dir),
        circuit_model_path=Path(ns.circuit_model_path),
        reserve_soc_pct=float(ns.reserve_soc_pct),
        min_turnaround_min=float(ns.min_turnaround_min),
        lookahead=int(ns.lookahead),
    )


def main() -> None:
    cfg = parse_args()
    spec = json.loads(cfg.windows_path.read_text())
    plane_id = str(spec.get("plane_id", "166"))
    total_flights = int(spec.get("total_flights", 0))
    circuits_per_flight = spec.get("circuits_per_flight", 1)
    if isinstance(circuits_per_flight, list):
        circuits_list = [int(v) for v in circuits_per_flight]
    else:
        circuits_list = [int(circuits_per_flight)] * total_flights

    flight_windows = sorted(spec.get("flight_windows", []), key=lambda w: w["start_min"])
    charge_windows = sorted(spec.get("charge_windows", []), key=lambda w: w["start_min"])
    charge_rate_default = float(spec.get("charge_rate_pct_per_min", 1.0))
    flight_duration_min = float(spec.get("flight_duration_min", 30.0))

    payload = _load_degradation_model(cfg.models_dir, cfg.model_name)
    model = payload["model"]
    scaler = payload["scaler"]
    bundle = payload["bundle"]
    feature_names = bundle["feature_names"]
    medians = bundle["feature_medians"]
    target_name = bundle.get("target_name", "delta_soh")

    circuit_meta = _load_circuit_model(cfg.circuit_model_path)
    soh_grid = circuit_meta["poh_soh_grid"]
    soc_grid = circuit_meta["poh_circuit_soc"]
    k_plane = circuit_meta.get("k_plane", {}).get(plane_id, circuit_meta.get("default_k", 1.0))

    current_soc = float(spec.get("initial_soc_pct", 100.0))
    current_soh = float(spec.get("initial_soh_pct", 95.0))
    rated_capacity_ah = float(spec.get("rated_capacity_ah", 29.0))
    current_cum_ah = float(spec.get("initial_cumulative_ah", 0.0))
    current_cum_cycles = float(spec.get("initial_cumulative_cycles", 0.0))
    current_cum_efc = float(spec.get("initial_cumulative_efc", 0.0))
    current_time = float(spec.get("start_min", 0.0))

    scheduled = []
    charge_events = []

    for flight_idx in range(total_flights):
        candidates = [w for w in flight_windows if w["start_min"] >= current_time]
        if not candidates:
            break
        candidates = candidates[: max(cfg.lookahead, 1)]

        best = None
        for window in candidates:
            sim_soc, sim_soh, sim_cum_ah, sim_cum_cycles, sim_cum_efc, sim_time, sim_charges = _apply_charge_windows(
                current_soc,
                current_soh,
                current_cum_ah,
                current_cum_cycles,
                current_cum_efc,
                current_time,
                float(window["start_min"]),
                charge_windows,
                charge_rate_default,
                cfg.reserve_soc_pct,
                payload,
                rated_capacity_ah,
            )
            circuits = circuits_list[min(flight_idx, len(circuits_list) - 1)]
            soc_per_circuit = k_plane * _poh_soc_per_circuit(sim_soh, soh_grid, soc_grid)
            soc_span = circuits * soc_per_circuit
            soc_end = sim_soc - soc_span
            if soc_end < cfg.reserve_soc_pct:
                continue

            delta_days = max((float(window["start_min"]) - sim_time) / 1440.0, 0.5 / 24.0)
            delta_ah = rated_capacity_ah * abs(soc_span) / 100.0
            future_cum_ah = sim_cum_ah + delta_ah
            delta_cycles = float(window.get("cycles", circuits))
            future_cum_cycles = sim_cum_cycles + delta_cycles
            delta_efc = abs(soc_span) / 100.0
            future_cum_efc = sim_cum_efc + delta_efc
            feature_row = _build_feature_row(
                feature_names,
                medians,
                "flight",
                delta_days,
                soc_span,
                delta_ah,
                future_cum_ah,
                delta_cycles,
                future_cum_cycles,
                delta_efc,
                future_cum_efc,
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
            else:
                pred_delta = pred
            score = pred_delta

            if best is None or score < best["score"]:
                best = {
                    "window": window,
                    "score": score,
                    "sim_soc": sim_soc,
                    "sim_soh": sim_soh,
                    "sim_time": sim_time,
                    "sim_charges": sim_charges,
                    "soc_end": soc_end,
                    "soc_span": soc_span,
                    "pred_delta": pred_delta,
                    "sim_cum_ah": sim_cum_ah,
                    "delta_ah": delta_ah,
                    "sim_cum_cycles": sim_cum_cycles,
                    "delta_cycles": delta_cycles,
                    "sim_cum_efc": sim_cum_efc,
                    "delta_efc": delta_efc,
                }

        if best is None:
            break

        # apply selected window
        charge_events.extend(best["sim_charges"])
        current_soc = best["soc_end"]
        current_soh = best["sim_soh"] + best["pred_delta"]
        current_cum_ah = best["sim_cum_ah"] + best["delta_ah"]
        current_cum_cycles = best["sim_cum_cycles"] + best["delta_cycles"]
        current_cum_efc = best["sim_cum_efc"] + best["delta_efc"]
        current_time = float(best["window"]["start_min"]) + flight_duration_min
        scheduled.append(
            {
                "type": "flight",
                "start_min": float(best["window"]["start_min"]),
                "duration_min": flight_duration_min,
                "circuits": circuits_list[min(flight_idx, len(circuits_list) - 1)],
                "cycles": float(best["delta_cycles"]),
                "soc_start_pct": float(best["sim_soc"]),
                "soc_end_pct": float(best["soc_end"]),
                "soh_start_pct": float(best["sim_soh"]),
                "soh_end_pct": float(current_soh),
                "pred_delta_soh": float(best["pred_delta"]),
            }
        )

    output = {
        "summary": {
            "scheduled_flights": int(len(scheduled)),
            "target_flights": int(total_flights),
            "reserve_soc_pct": float(cfg.reserve_soc_pct),
            "model_name": cfg.model_name,
        },
        "flights": scheduled,
        "charges": charge_events,
    }
    out_path = cfg.windows_path.with_suffix(".optimized.json")
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
