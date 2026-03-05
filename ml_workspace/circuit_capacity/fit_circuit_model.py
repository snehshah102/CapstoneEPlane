from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LATENT_ROOT = PROJECT_ROOT / "ml_workspace" / "latent_soh" / "output"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "ml_workspace" / "circuit_capacity" / "output"


POH_SOH_GRID = np.array([0, 20, 40, 60, 80, 100], dtype=float)
POH_CIRCUIT_SOC = np.array([20, 16, 13, 12, 10, 9], dtype=float)  # generic traffic pattern row


@dataclass
class Config:
    planes: list[str]
    latent_root: Path = DEFAULT_LATENT_ROOT
    output_root: Path = DEFAULT_OUTPUT_ROOT
    min_flight_events: int = 20
    train_frac: float = 0.70
    valid_frac: float = 0.15


def _parse_planes(value: str) -> list[str]:
    planes = [p.strip() for p in value.split(",") if p.strip()]
    return planes or ["166", "192"]


def _poh_soc_per_circuit(soh_pct: np.ndarray) -> np.ndarray:
    return np.interp(soh_pct, POH_SOH_GRID, POH_CIRCUIT_SOC)


def _load_plane_latent(latent_root: Path, plane_id: str) -> pd.DataFrame:
    path = latent_root / f"plane_{plane_id}" / "latent_soh_event_table.csv"
    df = pd.read_csv(path, parse_dates=["event_datetime"])
    df["plane_id"] = df["plane_id"].astype(str)
    df["battery_id"] = pd.to_numeric(df["battery_id"], errors="coerce")
    return df


def _time_split(df: pd.DataFrame, train_frac: float, valid_frac: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = df.sort_values("event_datetime").reset_index(drop=True)
    n = len(work)
    n_train = max(1, int(round(n * train_frac)))
    n_valid = max(1, int(round(n * valid_frac))) if n >= 3 else max(0, n - n_train)
    if n_train + n_valid >= n:
        n_valid = max(1, n - n_train - 1) if n >= 3 else max(0, n - n_train)
    n_test = n - n_train - n_valid
    if n_test <= 0 and n >= 3:
        n_test = 1
        if n_valid > 1:
            n_valid -= 1
        else:
            n_train -= 1
    train = work.iloc[:n_train].copy()
    valid = work.iloc[n_train : n_train + n_valid].copy()
    test = work.iloc[n_train + n_valid :].copy()
    return train, valid, test


def _calibrate_k(group: pd.DataFrame) -> float:
    soc_span = pd.to_numeric(group["soc_span_pct"], errors="coerce").to_numpy(dtype=float)
    soh = pd.to_numeric(group["latent_soh_smooth_pct"], errors="coerce").to_numpy(dtype=float)
    base = _poh_soc_per_circuit(soh)
    mask = np.isfinite(soc_span) & np.isfinite(base) & (base > 0.1)
    soc_span = soc_span[mask]
    base = base[mask]
    if len(soc_span) < 5:
        return 1.0
    k_grid = np.linspace(0.6, 1.4, 81)
    best_k = 1.0
    best_score = None
    for k in k_grid:
        circuits = soc_span / (k * base)
        score = np.mean(np.abs(circuits - np.round(circuits)))
        if best_score is None or score < best_score:
            best_score = score
            best_k = float(k)
    return best_k


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Fit circuit capacity and SOC-rate models.")
    parser.add_argument("--planes", default="166,192", help="Comma-separated plane IDs.")
    parser.add_argument("--latent-root", default=str(DEFAULT_LATENT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--min-flight-events", type=int, default=20)
    ns = parser.parse_args()
    return Config(
        planes=_parse_planes(ns.planes),
        latent_root=Path(ns.latent_root),
        output_root=Path(ns.output_root),
        min_flight_events=int(ns.min_flight_events),
    )


def main() -> None:
    cfg = parse_args()
    cfg.output_root.mkdir(parents=True, exist_ok=True)

    parts = []
    for plane_id in cfg.planes:
        parts.append(_load_plane_latent(cfg.latent_root, plane_id))
    df = pd.concat(parts, ignore_index=True)

    flights = df.loc[df["event_type"] == "flight"].copy()
    flights["soc_drop_pct"] = pd.to_numeric(flights["soc_span_pct"], errors="coerce")
    flights["flight_duration_min"] = pd.to_numeric(flights["event_duration_s"], errors="coerce") / 60.0
    flights["soc_rate_pct_per_min"] = flights["soc_drop_pct"] / flights["flight_duration_min"].clip(lower=1.0)

    circuit_rows = []
    k_plane = {}
    for plane_id, plane_group in flights.groupby("plane_id", sort=False):
        k_batt = {}
        for battery_id, g in plane_group.groupby("battery_id", sort=False):
            if len(g) < cfg.min_flight_events:
                continue
            k_batt[str(int(battery_id))] = _calibrate_k(g)
        if k_batt:
            k_plane[plane_id] = float(np.mean(list(k_batt.values())))
        for battery_id, g in plane_group.groupby("battery_id", sort=False):
            if len(g) < cfg.min_flight_events:
                k_value = k_plane.get(plane_id, 1.0)
            else:
                k_value = k_batt.get(str(int(battery_id)), 1.0)
            circuit_rows.append(
                {
                    "plane_id": str(plane_id),
                    "battery_id": int(battery_id),
                    "k_plane_batt": float(k_value),
                    "n_flights": int(len(g)),
                }
            )

    circuit_df = pd.DataFrame(circuit_rows)
    circuit_path = cfg.output_root / "circuit_calibration.csv"
    circuit_df.to_csv(circuit_path, index=False)

    model_meta = {
        "k_plane": k_plane,
        "default_k": 1.0,
        "poh_soh_grid": POH_SOH_GRID.tolist(),
        "poh_circuit_soc": POH_CIRCUIT_SOC.tolist(),
        "reserve_soc_pct": 30.0,
    }
    (cfg.output_root / "circuit_model.json").write_text(json.dumps(model_meta, indent=2))

    # SOC-rate regression
    feature_cols = [
        "latent_soh_smooth_pct",
        "current_abs_mean_a",
        "p95_abs_current_a",
        "avg_cell_temp_mean_c",
        "voltage_mean_v",
        "soc_min_pct",
        "soc_max_pct",
        "p95_abs_dcurrent_a_per_s",
        "kalman_coulomb_gap_mean_pct",
    ]
    flights = flights.dropna(subset=["soc_rate_pct_per_min"])
    flights = flights.loc[flights["soc_rate_pct_per_min"].between(0.0, 10.0)]

    plane_166 = flights.loc[flights["plane_id"] == "166"].copy()
    plane_192 = flights.loc[flights["plane_id"] == "192"].copy()
    train_df, valid_df, test_df = _time_split(plane_166, cfg.train_frac, cfg.valid_frac)

    def _prep(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        X = df[feature_cols].apply(pd.to_numeric, errors="coerce")
        med = X.median().fillna(0.0)
        return X.fillna(med), med

    X_train, medians = _prep(train_df)
    y_train = train_df["soc_rate_pct_per_min"].to_numpy(dtype=float)
    X_valid = valid_df[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(medians)
    y_valid = valid_df["soc_rate_pct_per_min"].to_numpy(dtype=float)
    X_test = test_df[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(medians)
    y_test = test_df["soc_rate_pct_per_min"].to_numpy(dtype=float)

    model = LinearRegression()
    model.fit(X_train, y_train)

    def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
        if len(y_true) == 0:
            return {"mae": np.nan, "rmse": np.nan, "r2": np.nan}
        err = y_pred - y_true
        mae = float(np.mean(np.abs(err)))
        rmse = float(np.sqrt(np.mean(err**2)))
        denom = float(np.sum((y_true - np.mean(y_true)) ** 2))
        r2 = float(1.0 - np.sum(err**2) / denom) if denom > 1e-12 else np.nan
        return {"mae": mae, "rmse": rmse, "r2": r2}

    metrics = {
        "train_metrics": _metrics(y_train, model.predict(X_train)),
        "valid_metrics": _metrics(y_valid, model.predict(X_valid)),
        "test_metrics": _metrics(y_test, model.predict(X_test)),
    }

    if not plane_192.empty:
        X_ood = plane_192[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(medians)
        y_ood = plane_192["soc_rate_pct_per_min"].to_numpy(dtype=float)
        metrics["ood_metrics"] = _metrics(y_ood, model.predict(X_ood))

    joblib.dump({"model": model, "feature_cols": feature_cols, "feature_medians": medians.to_dict()}, cfg.output_root / "soc_rate_model.joblib")
    (cfg.output_root / "soc_rate_model_metrics.json").write_text(json.dumps(metrics, indent=2))

    print(f"Wrote {circuit_path}")
    print(f"Wrote {cfg.output_root / 'circuit_model.json'}")
    print(f"Wrote {cfg.output_root / 'soc_rate_model.joblib'}")
    print(f"Wrote {cfg.output_root / 'soc_rate_model_metrics.json'}")


if __name__ == "__main__":
    main()
