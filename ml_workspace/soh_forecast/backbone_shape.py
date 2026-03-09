from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import mean_absolute_error


@dataclass
class BackboneFit:
    model: IsotonicRegression
    grid: pd.DataFrame
    source_points: pd.DataFrame


@dataclass
class PlaneBackboneCalibration:
    battery_id: int | str
    start_progress: float
    total_life_flights_from_start: float
    end_progress_observed: float
    fitted_mae: float
    flights_remaining_to_zero: float
    last_observed_soh_pct: float


def estimate_evtol_eol_index(anchor_df: pd.DataFrame, min_tail_points: int = 5) -> float | None:
    g = anchor_df.sort_values("mission_discharge_index").copy()
    x = pd.to_numeric(g["mission_discharge_index"], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(g["adjusted_health_pct"], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x = x[valid]
    y = y[valid]
    if len(x) < 2:
        return None
    zero_mask = y <= 0.0
    if zero_mask.any():
        return float(x[np.argmax(zero_mask)])
    tail_n = min(min_tail_points, len(x))
    x_tail = x[-tail_n:]
    y_tail = y[-tail_n:]
    if len(np.unique(x_tail)) < 2:
        return None
    slope, intercept = np.polyfit(x_tail, y_tail, 1)
    if slope >= -1e-6:
        return None
    eol_x = -intercept / slope
    if not np.isfinite(eol_x) or eol_x <= x[-1]:
        return None
    return float(eol_x)


def build_evtol_backbone_points(anchor_df: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for file_id, g in anchor_df.groupby("file_id"):
        eol_index = estimate_evtol_eol_index(g)
        if eol_index is None or eol_index <= 0:
            continue
        part = g.sort_values("mission_discharge_index").copy()
        part["progress"] = pd.to_numeric(part["mission_discharge_index"], errors="coerce") / eol_index
        part["progress"] = part["progress"].clip(lower=0.0, upper=1.0)
        part["health_pct"] = pd.to_numeric(part["adjusted_health_clipped_pct"], errors="coerce").clip(lower=0.0, upper=100.0)
        part["weight"] = 1.0
        part["source"] = "evtol"
        part["life_scale"] = eol_index
        parts.append(part[["source", "file_id", "progress", "health_pct", "weight", "life_scale"]])
    if not parts:
        return pd.DataFrame(columns=["source", "file_id", "progress", "health_pct", "weight", "life_scale"])
    return pd.concat(parts, ignore_index=True)


def fit_backbone(points_df: pd.DataFrame, n_grid: int = 201) -> BackboneFit:
    data = points_df.copy()
    data = data.loc[data["progress"].between(0.0, 1.0)].copy()
    data["progress"] = pd.to_numeric(data["progress"], errors="coerce")
    data["health_pct"] = pd.to_numeric(data["health_pct"], errors="coerce")
    data["weight"] = pd.to_numeric(data.get("weight", 1.0), errors="coerce").fillna(1.0)
    data = data.dropna(subset=["progress", "health_pct"]).sort_values("progress")
    model = IsotonicRegression(increasing=False, y_min=0.0, y_max=100.0, out_of_bounds="clip")
    model.fit(data["progress"], data["health_pct"], sample_weight=data["weight"])
    grid_progress = np.linspace(0.0, 1.0, n_grid)
    grid = pd.DataFrame({"progress": grid_progress, "health_pct": model.predict(grid_progress)})
    return BackboneFit(model=model, grid=grid, source_points=data)


def predict_backbone(backbone: BackboneFit, progress: np.ndarray | pd.Series | list[float]) -> np.ndarray:
    progress_arr = np.asarray(progress, dtype=float)
    progress_arr = np.clip(progress_arr, 0.0, 1.0)
    return np.asarray(backbone.model.predict(progress_arr), dtype=float)


def calibrate_plane_battery(
    battery_df: pd.DataFrame,
    backbone: BackboneFit,
    start_progress_grid: np.ndarray | None = None,
    total_life_grid: np.ndarray | None = None,
) -> PlaneBackboneCalibration:
    g = battery_df.sort_values("cumulative_flight_count").copy()
    x = pd.to_numeric(g["cumulative_flight_count"], errors="coerce").to_numpy(dtype=float)
    x = x - np.nanmin(x)
    y = pd.to_numeric(g["current_soh_pct"], errors="coerce").to_numpy(dtype=float)
    max_x = float(np.nanmax(x))

    if start_progress_grid is None:
        start_progress_grid = np.linspace(0.0, 0.70, 141)
    if total_life_grid is None:
        lower = max(max_x + 50.0, 150.0)
        total_life_grid = np.unique(np.round(np.geomspace(lower, 5000.0, 80), 3))

    best = None
    best_mae = float("inf")
    for start_progress in start_progress_grid:
        for total_life in total_life_grid:
            progress = start_progress + (x / total_life)
            if np.nanmax(progress) >= 1.0:
                continue
            pred = predict_backbone(backbone, progress)
            mae = mean_absolute_error(y, pred)
            if mae < best_mae:
                best_mae = mae
                best = (float(start_progress), float(total_life), float(np.nanmax(progress)), pred)

    if best is None:
        raise RuntimeError("Could not calibrate plane battery to backbone")

    start_progress, total_life, end_progress, _pred = best
    remaining = max((1.0 - end_progress) * total_life, 0.0)
    return PlaneBackboneCalibration(
        battery_id=g["battery_id"].iloc[0],
        start_progress=start_progress,
        total_life_flights_from_start=total_life,
        end_progress_observed=end_progress,
        fitted_mae=float(best_mae),
        flights_remaining_to_zero=float(remaining),
        last_observed_soh_pct=float(y[-1]),
    )


def add_plane_backbone_points(
    plane_df: pd.DataFrame,
    calibrations: list[PlaneBackboneCalibration],
    plane_weight: float = 3.0,
) -> pd.DataFrame:
    calib_by_batt = {str(c.battery_id): c for c in calibrations}
    parts: list[pd.DataFrame] = []
    for battery_id, g in plane_df.groupby("battery_id"):
        calib = calib_by_batt.get(str(battery_id)) or calib_by_batt.get(battery_id)
        if calib is None:
            continue
        part = g.sort_values("cumulative_flight_count").copy()
        flight_count = pd.to_numeric(part["cumulative_flight_count"], errors="coerce").to_numpy(dtype=float)
        flight_count = flight_count - np.nanmin(flight_count)
        part["progress"] = calib.start_progress + flight_count / calib.total_life_flights_from_start
        part["progress"] = part["progress"].clip(lower=0.0, upper=1.0)
        part["health_pct"] = pd.to_numeric(part["current_soh_pct"], errors="coerce").clip(lower=0.0, upper=100.0)
        part["weight"] = float(plane_weight)
        part["source"] = "plane"
        part["file_id"] = f"plane_batt_{battery_id}"
        part["life_scale"] = calib.total_life_flights_from_start
        parts.append(part[["source", "file_id", "progress", "health_pct", "weight", "life_scale"]])
    if not parts:
        return pd.DataFrame(columns=["source", "file_id", "progress", "health_pct", "weight", "life_scale"])
    return pd.concat(parts, ignore_index=True)


def build_plane_backbone_trajectory(
    battery_df: pd.DataFrame,
    backbone: BackboneFit,
    calibration: PlaneBackboneCalibration,
    n_future: int = 400,
) -> pd.DataFrame:
    g = battery_df.sort_values("cumulative_flight_count").copy()
    flight_count = pd.to_numeric(g["cumulative_flight_count"], errors="coerce").to_numpy(dtype=float)
    min_flight = float(np.nanmin(flight_count))
    max_flight = float(np.nanmax(flight_count))
    eol_flight = min_flight + calibration.total_life_flights_from_start
    future_end = max(eol_flight, max_flight + n_future)
    x_grid = np.linspace(min_flight, future_end, 300)
    progress = calibration.start_progress + (x_grid - min_flight) / calibration.total_life_flights_from_start
    health = predict_backbone(backbone, progress)
    return pd.DataFrame(
        {
            "battery_id": calibration.battery_id,
            "cumulative_flight_count": x_grid,
            "progress": np.clip(progress, 0.0, 1.0),
            "backbone_soh_pct": health,
            "is_forecast": x_grid > max_flight,
        }
    )
