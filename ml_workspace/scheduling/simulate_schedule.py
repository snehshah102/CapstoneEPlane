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
    schedule_path: Path
    model_name: str
    models_dir: Path = DEFAULT_FORECAST_MODELS
    circuit_model_path: Path = DEFAULT_CIRCUIT_MODEL
    min_turnaround_min: float = 30.0
    reserve_soc_pct: float = 30.0


def _load_degradation_model(models_dir: Path, model_name: str) -> dict[str, Any]:
    payload = joblib.load(models_dir / f"{model_name}.joblib")
    return payload


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


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Simulate a flight/charge schedule with SOH degradation.")
    parser.add_argument("--schedule-path", required=True, help="Path to schedule JSON.")
    parser.add_argument("--model-name", default="elastic_net")
    parser.add_argument("--models-dir", default=str(DEFAULT_FORECAST_MODELS))
    parser.add_argument("--circuit-model-path", default=str(DEFAULT_CIRCUIT_MODEL))
    parser.add_argument("--min-turnaround-min", type=float, default=30.0)
    parser.add_argument("--reserve-soc-pct", type=float, default=30.0)
    return Config(
        schedule_path=Path(parser.parse_args().schedule_path),
        model_name=parser.parse_args().model_name,
        models_dir=Path(parser.parse_args().models_dir),
        circuit_model_path=Path(parser.parse_args().circuit_model_path),
        min_turnaround_min=float(parser.parse_args().min_turnaround_min),
        reserve_soc_pct=float(parser.parse_args().reserve_soc_pct),
    )


def main() -> None:
    cfg = parse_args()
    schedule = json.loads(cfg.schedule_path.read_text())
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
    k_plane = circuit_meta.get("k_plane", {}).get(str(schedule.get("plane_id", "166")), circuit_meta.get("default_k", 1.0))

    events = schedule.get("events", [])
    events = sorted(events, key=lambda e: e.get("start_min", 0))
    if not events:
        raise ValueError("schedule has no events")

    current_soc = float(schedule.get("initial_soc_pct", 100.0))
    current_soh = float(schedule.get("initial_soh_pct", 95.0))
    rated_capacity_ah = float(schedule.get("rated_capacity_ah", 29.0))
    cumulative_ah = float(schedule.get("initial_cumulative_ah", 0.0))
    cumulative_cycles = float(schedule.get("initial_cumulative_cycles", 0.0))
    cumulative_efc = float(schedule.get("initial_cumulative_efc", 0.0))
    last_start = None

    results = []
    total_degradation = 0.0
    min_soc = current_soc
    violated_reserve = False

    for idx, event in enumerate(events):
        event_type = event["type"]
        start_min = event.get("start_min")
        if start_min is None:
            if last_start is None:
                start_min = 0.0
            else:
                start_min = last_start + cfg.min_turnaround_min
        duration_min = float(event.get("duration_min", 0.0))

        if last_start is None:
            delta_days = 0.5 / 24.0
        else:
            delta_days = max((start_min - last_start) / 1440.0, 0.5 / 24.0)

        if event_type == "flight":
            circuits = int(event.get("circuits", 1))
            soc_per_circuit = k_plane * _poh_soc_per_circuit(current_soh, soh_grid, soc_grid)
            soc_span = circuits * soc_per_circuit
            soc_end = current_soc - soc_span
            delta_cycles = float(event.get("cycles", event.get("circuits", 1)))
        elif event_type == "charge":
            charge_rate = float(event.get("charge_rate_pct_per_min", 1.0))
            soc_end = min(100.0, current_soc + charge_rate * duration_min)
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

        if soc_end < cfg.reserve_soc_pct:
            violated_reserve = True
        min_soc = min(min_soc, soc_end)

        results.append(
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
                "delta_days": float(delta_days),
            }
        )

        current_soc = soc_end
        current_soh = soh_end
        last_start = start_min

    output = {
        "summary": {
            "total_pred_delta_soh": float(total_degradation),
            "min_soc_pct": float(min_soc),
            "reserve_soc_pct": float(cfg.reserve_soc_pct),
            "violated_reserve": bool(violated_reserve),
            "model_name": cfg.model_name,
        },
        "events": results,
    }

    out_path = cfg.schedule_path.with_suffix(".simulated.json")
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
