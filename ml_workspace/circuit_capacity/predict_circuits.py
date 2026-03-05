from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "ml_workspace" / "circuit_capacity" / "output" / "circuit_model.json"
DEFAULT_RATE_MODEL_PATH = PROJECT_ROOT / "ml_workspace" / "circuit_capacity" / "output" / "soc_rate_model.joblib"


@dataclass(frozen=True)
class CircuitCapacityArtifacts:
    model_meta: dict[str, Any]
    rate_model: Any
    feature_cols: list[str]
    feature_medians: dict[str, float]


@dataclass(frozen=True)
class CircuitCapacityPrediction:
    plane_id: str
    battery_id: int
    soh_pct: float
    soc_start_pct: float
    soc_per_circuit_pct: float
    circuits_max: int
    soc_rate_pct_per_min: float
    reserve_soc_pct: float
    usable_soc_window_pct: float


def _poh_soc_per_circuit(soh_pct: float, soh_grid: Sequence[float], soc_grid: Sequence[float]) -> float:
    return float(np.interp(soh_pct, np.array(soh_grid, dtype=float), np.array(soc_grid, dtype=float)))


def load_capacity_artifacts(
    model_path: Path | str = DEFAULT_MODEL_PATH,
    rate_model_path: Path | str = DEFAULT_RATE_MODEL_PATH,
) -> CircuitCapacityArtifacts:
    model_meta = json.loads(Path(model_path).read_text())
    rate_payload = joblib.load(rate_model_path)
    return CircuitCapacityArtifacts(
        model_meta=model_meta,
        rate_model=rate_payload["model"],
        feature_cols=list(rate_payload["feature_cols"]),
        feature_medians={str(k): float(v) for k, v in rate_payload["feature_medians"].items()},
    )


def estimate_soc_per_circuit(
    soh_pct: float,
    plane_id: str,
    artifacts: CircuitCapacityArtifacts,
) -> float:
    model_meta = artifacts.model_meta
    soh_grid = model_meta["poh_soh_grid"]
    soc_grid = model_meta["poh_circuit_soc"]
    k_plane = model_meta.get("k_plane", {}).get(str(plane_id), model_meta.get("default_k", 1.0))
    return float(k_plane) * _poh_soc_per_circuit(soh_pct, soh_grid, soc_grid)


def _coerce_feature_value(value: float | None, fallback: float) -> float:
    if value is None:
        return float(fallback)
    if not np.isfinite(value):
        return float(fallback)
    return float(value)


def build_rate_feature_row(
    soh_pct: float,
    artifacts: CircuitCapacityArtifacts,
    feature_inputs: Mapping[str, float] | None = None,
) -> dict[str, float]:
    feature_inputs = feature_inputs or {}
    feature_map = {
        "latent_soh_smooth_pct": soh_pct,
        "current_abs_mean_a": feature_inputs.get("current_abs_mean_a"),
        "p95_abs_current_a": feature_inputs.get("p95_abs_current_a"),
        "avg_cell_temp_mean_c": feature_inputs.get("avg_cell_temp_mean_c"),
        "voltage_mean_v": feature_inputs.get("voltage_mean_v"),
        "soc_min_pct": feature_inputs.get("soc_min_pct"),
        "soc_max_pct": feature_inputs.get("soc_max_pct"),
        "p95_abs_dcurrent_a_per_s": feature_inputs.get("p95_abs_dcurrent_a_per_s"),
        "kalman_coulomb_gap_mean_pct": feature_inputs.get("kalman_coulomb_gap_mean_pct"),
    }
    row: dict[str, float] = {}
    for col in artifacts.feature_cols:
        row[col] = _coerce_feature_value(feature_map.get(col), artifacts.feature_medians.get(col, 0.0))
    return row


def predict_circuit_capacity(
    soh_pct: float,
    plane_id: str = "166",
    battery_id: int = 1,
    soc_start_pct: float | None = None,
    soc_max_pct: float | None = None,
    feature_inputs: Mapping[str, float] | None = None,
    artifacts: CircuitCapacityArtifacts | None = None,
    model_path: Path | str = DEFAULT_MODEL_PATH,
    rate_model_path: Path | str = DEFAULT_RATE_MODEL_PATH,
) -> CircuitCapacityPrediction:
    artifacts = artifacts or load_capacity_artifacts(model_path=model_path, rate_model_path=rate_model_path)
    reserve = float(artifacts.model_meta.get("reserve_soc_pct", 30.0))

    soc_per_circuit = estimate_soc_per_circuit(soh_pct=soh_pct, plane_id=str(plane_id), artifacts=artifacts)
    inferred_soc_start = soc_start_pct
    if inferred_soc_start is None or not np.isfinite(inferred_soc_start):
        inferred_soc_start = soc_max_pct if soc_max_pct is not None and np.isfinite(soc_max_pct) else 100.0

    usable_soc_window = max(0.0, float(inferred_soc_start) - reserve)
    circuits_max = int(max(0.0, np.floor(usable_soc_window / max(soc_per_circuit, 0.1))))
    row = build_rate_feature_row(soh_pct=soh_pct, artifacts=artifacts, feature_inputs=feature_inputs)
    row_df = pd.DataFrame([row], columns=artifacts.feature_cols)
    soc_rate = float(artifacts.rate_model.predict(row_df)[0])

    return CircuitCapacityPrediction(
        plane_id=str(plane_id),
        battery_id=int(battery_id),
        soh_pct=float(soh_pct),
        soc_start_pct=float(inferred_soc_start),
        soc_per_circuit_pct=float(soc_per_circuit),
        circuits_max=int(circuits_max),
        soc_rate_pct_per_min=float(soc_rate),
        reserve_soc_pct=float(reserve),
        usable_soc_window_pct=float(usable_soc_window),
    )


def build_capacity_sweep(
    soh_values: Sequence[float],
    plane_id: str = "166",
    battery_id: int = 1,
    soc_start_pct: float = 100.0,
    feature_inputs: Mapping[str, float] | None = None,
    artifacts: CircuitCapacityArtifacts | None = None,
    model_path: Path | str = DEFAULT_MODEL_PATH,
    rate_model_path: Path | str = DEFAULT_RATE_MODEL_PATH,
) -> pd.DataFrame:
    artifacts = artifacts or load_capacity_artifacts(model_path=model_path, rate_model_path=rate_model_path)
    rows = [
        asdict(
            predict_circuit_capacity(
                soh_pct=float(soh_pct),
                plane_id=plane_id,
                battery_id=battery_id,
                soc_start_pct=soc_start_pct,
                feature_inputs=feature_inputs,
                artifacts=artifacts,
            )
        )
        for soh_pct in soh_values
    ]
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict circuits capacity and SOC rate.")
    parser.add_argument("--plane-id", default="166")
    parser.add_argument("--battery-id", type=int, default=1)
    parser.add_argument("--soh-pct", type=float, required=True)
    parser.add_argument("--soc-start-pct", type=float, default=np.nan)
    parser.add_argument("--soc-max-pct", type=float, default=np.nan)
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--rate-model-path", default=str(DEFAULT_RATE_MODEL_PATH))
    parser.add_argument("--output-path", default="")
    parser.add_argument("--current-abs-mean-a", type=float, default=np.nan)
    parser.add_argument("--p95-abs-current-a", type=float, default=np.nan)
    parser.add_argument("--avg-cell-temp-mean-c", type=float, default=np.nan)
    parser.add_argument("--voltage-mean-v", type=float, default=np.nan)
    parser.add_argument("--soc-min-pct", type=float, default=np.nan)
    parser.add_argument("--soc-max-pct-feature", type=float, default=np.nan)
    parser.add_argument("--p95-abs-dcurrent-a-per-s", type=float, default=np.nan)
    parser.add_argument("--kalman-coulomb-gap-mean-pct", type=float, default=np.nan)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    feature_inputs = {
        "current_abs_mean_a": args.current_abs_mean_a,
        "p95_abs_current_a": args.p95_abs_current_a,
        "avg_cell_temp_mean_c": args.avg_cell_temp_mean_c,
        "voltage_mean_v": args.voltage_mean_v,
        "soc_min_pct": args.soc_min_pct,
        "soc_max_pct": args.soc_max_pct_feature,
        "p95_abs_dcurrent_a_per_s": args.p95_abs_dcurrent_a_per_s,
        "kalman_coulomb_gap_mean_pct": args.kalman_coulomb_gap_mean_pct,
    }
    prediction = predict_circuit_capacity(
        soh_pct=args.soh_pct,
        plane_id=str(args.plane_id),
        battery_id=int(args.battery_id),
        soc_start_pct=None if np.isnan(args.soc_start_pct) else float(args.soc_start_pct),
        soc_max_pct=None if np.isnan(args.soc_max_pct) else float(args.soc_max_pct),
        feature_inputs=feature_inputs,
        model_path=args.model_path,
        rate_model_path=args.rate_model_path,
    )
    result = asdict(prediction)

    if args.output_path:
        Path(args.output_path).write_text(json.dumps(result, indent=2))
        print(f"Wrote {args.output_path}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
