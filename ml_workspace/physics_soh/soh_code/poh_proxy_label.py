from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SOH_GRID = np.array([100, 80, 60, 40, 20, 0], dtype=float)

POH_PHASE_TABLE: list[tuple[str, str, list[float]]] = [
    (
        "takeoff_initial_climb_300",
        "Take off and initial climb to 300 ft AGL",
        [4, 4, 5, 6, 7, 8],
    ),
    ("climb_1000_vy_48kw", "1000 ft climb at Vy - 48 kW", [7, 7, 8, 10, 12, 14]),
    ("cruise_20kw_10min", "10 min cruise - 20 kW (69 KCAS)", [15, 17, 19, 22, 26, 32]),
    ("cruise_25kw_10min", "10 min cruise - 25 kW (78 KCAS)", [19, 22, 25, 28, 34, 41]),
    ("cruise_30kw_10min", "10 min cruise - 30 kW (86 KCAS)", [24, 26, 30, 35, 41, 50]),
    ("cruise_35kw_10min", "10 min cruise - 35 kW (92 KCAS)", [28, 31, 36, 41, 49, 59]),
    ("touch_and_go_climb_300", "Touch and go and climb to 300 ft AGL", [3, 3, 4, 4, 5, 6]),
    ("first_traffic_pattern", "Energy for the first traffic pattern", [10, 11, 13, 15, 18, 22]),
    ("generic_traffic_pattern", "Energy for a generic traffic pattern", [9, 10, 12, 13, 16, 20]),
    (
        "aborted_landing_climb_1000_64kw",
        "Aborted landing and climb to 1000 ft AGL at Vy - 64 kW",
        [7, 8, 9, 10, 12, 15],
    ),
]

POH_TABLE_BY_KEY = {k: np.array(v, dtype=float) for k, _, v in POH_PHASE_TABLE}
POH_NAME_BY_KEY = {k: n for k, n, _ in POH_PHASE_TABLE}
CRUISE_KEYS = ["cruise_20kw_10min", "cruise_25kw_10min", "cruise_30kw_10min", "cruise_35kw_10min"]
CRUISE_BINS_KW = np.array([20.0, 25.0, 30.0, 35.0], dtype=float)

PLOT_COLORS = {
    "takeoff_initial_climb_300": "#d62728",
    "climb_1000_vy_48kw": "#ff7f0e",
    "cruise_20kw_10min": "#2ca02c",
    "cruise_25kw_10min": "#17becf",
    "cruise_30kw_10min": "#1f77b4",
    "cruise_35kw_10min": "#9467bd",
    "touch_and_go_climb_300": "#8c564b",
    "first_traffic_pattern": "#e377c2",
    "generic_traffic_pattern": "#7f7f7f",
    "aborted_landing_climb_1000_64kw": "#bcbd22",
}


@dataclass
class Config:
    raw_root: Path
    out_dir: Path
    plane_id: str
    max_flights: int | None = None
    min_active_seconds: float = 600.0
    active_power_kw: float = 8.0
    active_ias_kts: float = 18.0
    phase_points_min: int = 30
    smooth_points: int = 41
    takeoff_power_kw: float = 22.0
    takeoff_ias_kts: float = 35.0
    ground_agl_ft: float = 100.0
    cruise_min_agl_ft: float = 700.0
    cruise_max_abs_climb_fpm: float = 200.0
    min_climb_fpm: float = 150.0
    cruise_min_seconds: float = 360.0
    cruise_target_seconds: float = 600.0
    min_pattern_seconds: float = 180.0
    segment_plot_count: int = 12


def normalize_col(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def parse_flight_id(folder_name: str) -> int | None:
    m = re.match(r"^(?P<fid>\d+)-csv-", folder_name)
    if m:
        return int(m.group("fid"))
    m = re.match(r"^(?P<fid>\d+)", folder_name)
    return int(m.group("fid")) if m else None


def discover_flights(raw_root: Path, max_flights: int | None) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for d in raw_root.iterdir():
        if not d.is_dir():
            continue
        fid = parse_flight_id(d.name)
        if fid is None:
            continue
        out.append((fid, d))
    out.sort(key=lambda item: (item[0], item[1].name))
    if max_flights is not None:
        out = out[:max_flights]
    return out


def find_main_csv(flight_dir: Path) -> Path | None:
    csvs = sorted(flight_dir.glob("*.csv"))
    main = [
        p for p in csvs if not p.name.lower().endswith(("_1.csv", "_2.csv", "_warns.csv"))
    ]
    return main[0] if main else None


def load_main_df(path: Path) -> pd.DataFrame:
    needed = {
        "time(ms)",
        "time(min)",
        "bat 1 soc",
        "bat 2 soc",
        "motor power",
        "ias",
        "pressure_alt",
        "ground_speed",
    }
    df = pd.read_csv(
        path,
        skipinitialspace=True,
        low_memory=False,
        usecols=lambda c: normalize_col(c) in needed,
    )
    df = df.rename(columns={c: normalize_col(c) for c in df.columns})
    if "time(ms)" not in df.columns:
        raise ValueError("Missing time(ms)")
    for col in [
        "time(min)",
        "bat 1 soc",
        "bat 2 soc",
        "motor power",
        "ias",
        "pressure_alt",
        "ground_speed",
    ]:
        if col not in df.columns:
            df[col] = np.nan
    for col in [
        "time(ms)",
        "time(min)",
        "bat 1 soc",
        "bat 2 soc",
        "motor power",
        "ias",
        "pressure_alt",
        "ground_speed",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time(ms)"]).sort_values("time(ms)").reset_index(drop=True)
    df = df.loc[df["time(ms)"].diff().fillna(1.0) > 0].copy()
    if df.empty:
        raise ValueError("No valid time rows")
    t0 = float(df["time(ms)"].iloc[0])
    df["time_s"] = (df["time(ms)"] - t0) / 1000.0
    return df


def contiguous_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    if mask.size == 0:
        return []
    runs: list[tuple[int, int]] = []
    i = 0
    n = int(mask.size)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i + 1
        while j < n and mask[j]:
            j += 1
        runs.append((i, j - 1))
        i = j
    return runs


def run_duration_seconds(t_s: np.ndarray, start: int, end: int) -> float:
    if end <= start:
        return 0.0
    return float(t_s[end] - t_s[start])


def pick_longest_active_run(df: pd.DataFrame, cfg: Config) -> tuple[int, int] | None:
    power = df["motor power"].fillna(0.0).to_numpy(dtype=float)
    ias = df["ias"].fillna(0.0).to_numpy(dtype=float) if "ias" in df.columns else np.zeros(len(df))
    active_raw = (power >= cfg.active_power_kw) | (ias >= cfg.active_ias_kts)
    if not np.any(active_raw):
        return None
    active = (
        pd.Series(active_raw)
        .rolling(window=15, center=True, min_periods=1)
        .max()
        .fillna(0)
        .astype(bool)
        .to_numpy()
    )
    t_s = df["time_s"].to_numpy(dtype=float)
    idx = np.flatnonzero(active)
    if idx.size == 0:
        return None
    best = (int(idx[0]), int(idx[-1]))
    if run_duration_seconds(t_s, best[0], best[1]) < cfg.min_active_seconds:
        return None
    return best


def first_true(mask: np.ndarray, start: int = 0) -> int | None:
    idx = np.flatnonzero(mask[start:])
    if idx.size == 0:
        return None
    return int(start + idx[0])


def append_phase(
    phases: list[dict[str, object]],
    key: str,
    start_idx: int | None,
    end_idx: int | None,
    t_s: np.ndarray,
    power: np.ndarray,
    ias: np.ndarray,
    agl_ft: np.ndarray,
    min_points: int,
) -> None:
    if start_idx is None or end_idx is None:
        return
    if end_idx <= start_idx:
        return
    if end_idx - start_idx + 1 < min_points:
        return
    phases.append(
        {
            "phase_key": key,
            "phase_name": POH_NAME_BY_KEY[key],
            "start_idx": int(start_idx),
            "end_idx": int(end_idx),
            "start_time_s": float(t_s[start_idx]),
            "end_time_s": float(t_s[end_idx]),
            "duration_s": float(t_s[end_idx] - t_s[start_idx]),
            "median_power_kw": float(np.nanmedian(power[start_idx : end_idx + 1])),
            "median_ias_kts": float(np.nanmedian(ias[start_idx : end_idx + 1])),
            "median_agl_ft": float(np.nanmedian(agl_ft[start_idx : end_idx + 1])),
        }
    )


def segment_phases(df_active: pd.DataFrame, cfg: Config) -> list[dict[str, object]]:
    t_s = df_active["time_s"].to_numpy(dtype=float)
    power = df_active["motor power"].fillna(0.0).to_numpy(dtype=float)
    ias = df_active["ias"].fillna(0.0).to_numpy(dtype=float)
    agl_ft = df_active["agl_ft"].fillna(0.0).to_numpy(dtype=float)

    power_sm = (
        pd.Series(power).rolling(window=cfg.smooth_points, center=True, min_periods=1).median().to_numpy()
    )
    if len(t_s) < 3 or np.allclose(t_s[-1], t_s[0]):
        return []

    climb_fpm = np.gradient(agl_ft, t_s, edge_order=1) * 60.0
    climb_sm = (
        pd.Series(climb_fpm)
        .rolling(window=cfg.smooth_points, center=True, min_periods=1)
        .median()
        .to_numpy()
    )

    phases: list[dict[str, object]] = []

    takeoff_start = first_true(
        (power_sm >= cfg.takeoff_power_kw) & (ias >= cfg.takeoff_ias_kts)
    )
    if takeoff_start is None:
        takeoff_start = first_true((power_sm >= cfg.takeoff_power_kw) & (agl_ft >= 20.0))
    p1_end = first_true(agl_ft >= 300.0, start=(takeoff_start or 0))
    append_phase(
        phases,
        "takeoff_initial_climb_300",
        takeoff_start,
        p1_end,
        t_s,
        power_sm,
        ias,
        agl_ft,
        cfg.phase_points_min,
    )

    p2_start = p1_end
    p2_end = None
    if p2_start is not None:
        p2_end = first_true((agl_ft >= 1300.0) & (climb_sm >= cfg.min_climb_fpm), start=p2_start)
        if p2_end is None:
            p2_end = first_true(agl_ft >= 1300.0, start=p2_start)
        if p2_end is None:
            p2_end = first_true((agl_ft >= 1000.0) & (climb_sm >= cfg.min_climb_fpm), start=p2_start)
        if p2_end is None:
            p2_end = first_true(agl_ft >= 1000.0, start=p2_start)
        if p2_end is None:
            rel_peak = int(np.argmax(agl_ft[p2_start:]))
            peak_idx = int(p2_start + rel_peak)
            if peak_idx > p2_start and (agl_ft[peak_idx] - agl_ft[p2_start]) >= 350.0:
                p2_end = peak_idx
    append_phase(
        phases,
        "climb_1000_vy_48kw",
        p2_start,
        p2_end,
        t_s,
        power_sm,
        ias,
        agl_ft,
        cfg.phase_points_min,
    )

    cruise_start = None
    cruise_end = None
    search_from = p2_end if p2_end is not None else (p1_end if p1_end is not None else 0)
    cruise_mask = (
        (np.abs(climb_sm) <= cfg.cruise_max_abs_climb_fpm)
        & (power_sm >= 15.0)
        & (power_sm <= 40.0)
        & (agl_ft >= cfg.cruise_min_agl_ft)
    )
    cruise_runs = contiguous_runs(cruise_mask[search_from:])
    if cruise_runs:
        global_runs = [(a + search_from, b + search_from) for a, b in cruise_runs]
        candidates = [
            r for r in global_runs if run_duration_seconds(t_s, r[0], r[1]) >= cfg.cruise_min_seconds
        ]
        if candidates:
            run = min(
                candidates,
                key=lambda r: abs(run_duration_seconds(t_s, r[0], r[1]) - cfg.cruise_target_seconds),
            )
            if run_duration_seconds(t_s, run[0], run[1]) > cfg.cruise_target_seconds:
                target_end_time = t_s[run[0]] + cfg.cruise_target_seconds
                idx = np.searchsorted(t_s, target_end_time, side="left")
                cruise_start = run[0]
                cruise_end = min(max(idx, run[0] + cfg.phase_points_min), run[1])
            else:
                cruise_start, cruise_end = run

    cruise_phase_key = None
    if cruise_start is not None and cruise_end is not None and cruise_end > cruise_start:
        p_med = float(np.nanmedian(power_sm[cruise_start : cruise_end + 1]))
        cruise_idx = int(np.argmin(np.abs(CRUISE_BINS_KW - p_med)))
        cruise_phase_key = CRUISE_KEYS[cruise_idx]
        append_phase(
            phases,
            cruise_phase_key,
            cruise_start,
            cruise_end,
            t_s,
            power_sm,
            ias,
            agl_ft,
            cfg.phase_points_min,
        )

    ground = agl_ft <= cfg.ground_agl_ft
    tg_start = None
    tg_anchor = cruise_end if cruise_end is not None else (p2_end if p2_end is not None else (p1_end if p1_end is not None else 0))
    if tg_anchor is not None and tg_anchor + 1 < len(ground):
        for idx in np.flatnonzero(ground[tg_anchor + 1 :]):
            gi = int(tg_anchor + 1 + idx)
            back = max(0, gi - 600)
            if np.nanmax(agl_ft[back:gi + 1]) >= 300.0:
                tg_start = gi
                break
    tg_end = None
    if tg_start is not None:
        tg_end = first_true((agl_ft >= 300.0) & (climb_sm >= cfg.min_climb_fpm), start=tg_start)
        if tg_end is None:
            tg_end = first_true(agl_ft >= 300.0, start=tg_start)
    append_phase(
        phases,
        "touch_and_go_climb_300",
        tg_start,
        tg_end,
        t_s,
        power_sm,
        ias,
        agl_ft,
        cfg.phase_points_min,
    )

    pattern1_start = tg_end
    if pattern1_start is None:
        pattern1_start = cruise_end if cruise_end is not None else (p2_end if p2_end is not None else p1_end)
    ground_after_tg = np.flatnonzero(ground[pattern1_start + 1 :]) if pattern1_start is not None else np.array([])
    pattern1_end = int(pattern1_start + 1 + ground_after_tg[0]) if ground_after_tg.size else None
    if pattern1_start is not None and pattern1_end is not None:
        if run_duration_seconds(t_s, pattern1_start, pattern1_end) < cfg.min_pattern_seconds:
            pattern1_end = None
    append_phase(
        phases,
        "first_traffic_pattern",
        pattern1_start,
        pattern1_end,
        t_s,
        power_sm,
        ias,
        agl_ft,
        cfg.phase_points_min,
    )

    pattern2_start = pattern1_end
    ground_after_pattern1 = (
        np.flatnonzero(ground[pattern2_start + 1 :]) if pattern2_start is not None else np.array([])
    )
    pattern2_end = int(pattern2_start + 1 + ground_after_pattern1[0]) if ground_after_pattern1.size else None
    if pattern2_start is not None and pattern2_end is not None:
        if run_duration_seconds(t_s, pattern2_start, pattern2_end) < cfg.min_pattern_seconds:
            pattern2_end = None
    append_phase(
        phases,
        "generic_traffic_pattern",
        pattern2_start,
        pattern2_end,
        t_s,
        power_sm,
        ias,
        agl_ft,
        cfg.phase_points_min,
    )

    abort_start = pattern2_end if pattern2_end is not None else (pattern1_end if pattern1_end is not None else tg_start)
    abort_end = None
    if abort_start is not None:
        abort_end = first_true(
            (agl_ft >= 1000.0) & (climb_sm >= cfg.min_climb_fpm) & (power_sm >= 45.0),
            start=abort_start,
        )
        if abort_end is None:
            abort_end = first_true((agl_ft >= 1000.0) & (climb_sm >= cfg.min_climb_fpm), start=abort_start)
    append_phase(
        phases,
        "aborted_landing_climb_1000_64kw",
        abort_start,
        abort_end,
        t_s,
        power_sm,
        ias,
        agl_ft,
        cfg.phase_points_min,
    )

    ordered = sorted(phases, key=lambda x: float(x["start_time_s"]))
    seen_cruise = [p for p in ordered if str(p["phase_key"]).startswith("cruise_")]
    if len(seen_cruise) > 1:
        keep_key = str(seen_cruise[0]["phase_key"]) if cruise_phase_key is None else cruise_phase_key
        ordered = [p for p in ordered if (not str(p["phase_key"]).startswith("cruise_")) or str(p["phase_key"]) == keep_key]
    return ordered


def interpolate_soc_from_soh(soh: float, phase_key: str) -> float:
    vals = POH_TABLE_BY_KEY[phase_key]
    return float(np.interp(soh, SOH_GRID[::-1], vals[::-1]))


def invert_soc_to_soh(delta_soc: float, phase_key: str) -> float:
    vals = POH_TABLE_BY_KEY[phase_key]
    if not np.isfinite(delta_soc):
        return np.nan
    if delta_soc <= vals[0]:
        return 100.0
    if delta_soc >= vals[-1]:
        return 0.0
    hi = int(np.searchsorted(vals, delta_soc, side="right"))
    lo = hi - 1
    x0, x1 = float(vals[lo]), float(vals[hi])
    y0, y1 = float(SOH_GRID[lo]), float(SOH_GRID[hi])
    if math.isclose(x1, x0):
        return float(y0)
    frac = (delta_soc - x0) / (x1 - x0)
    return float(np.clip(y0 + frac * (y1 - y0), 0.0, 100.0))


def safe_soc_delta(series: pd.Series, start_idx: int, end_idx: int) -> float:
    if end_idx <= start_idx:
        return np.nan
    s = pd.to_numeric(series, errors="coerce").clip(0, 100)
    v0 = float(s.iloc[start_idx]) if pd.notna(s.iloc[start_idx]) else np.nan
    v1 = float(s.iloc[end_idx]) if pd.notna(s.iloc[end_idx]) else np.nan
    if not np.isfinite(v0) or not np.isfinite(v1):
        return np.nan
    return float(v0 - v1)


def compute_labels_for_flight(
    flight_id: int,
    source_folder: str,
    df_active: pd.DataFrame,
    phases: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    phase_rows: list[dict[str, object]] = []
    flight_rows: list[dict[str, object]] = []

    batteries = [
        ("1", "bat 1 soc"),
        ("2", "bat 2 soc"),
        ("pack_avg", None),
    ]

    per_batt_phase: dict[str, list[dict[str, object]]] = {b: [] for b, _ in batteries}

    for phase in phases:
        sidx = int(phase["start_idx"])
        eidx = int(phase["end_idx"])
        key = str(phase["phase_key"])

        d1 = safe_soc_delta(df_active["bat 1 soc"], sidx, eidx) if "bat 1 soc" in df_active.columns else np.nan
        d2 = safe_soc_delta(df_active["bat 2 soc"], sidx, eidx) if "bat 2 soc" in df_active.columns else np.nan
        davg = float(np.nanmean([d1, d2])) if np.isfinite(d1) or np.isfinite(d2) else np.nan

        delta_by_batt = {"1": d1, "2": d2, "pack_avg": davg}

        for batt_id, _ in batteries:
            delta_soc = float(delta_by_batt[batt_id]) if np.isfinite(delta_by_batt[batt_id]) else np.nan
            inferred_soh = invert_soc_to_soh(delta_soc, key) if np.isfinite(delta_soc) else np.nan
            poh_soc_hat = interpolate_soc_from_soh(inferred_soh, key) if np.isfinite(inferred_soh) else np.nan
            fit_abs_err = float(abs(delta_soc - poh_soc_hat)) if np.isfinite(poh_soc_hat) else np.nan
            weight = float(max(delta_soc, 0.0)) if np.isfinite(delta_soc) else np.nan
            row = {
                "flight_id": flight_id,
                "source_folder": source_folder,
                "battery_id": batt_id,
                "phase_key": key,
                "phase_name": POH_NAME_BY_KEY[key],
                "start_time_s": float(phase["start_time_s"]),
                "end_time_s": float(phase["end_time_s"]),
                "duration_s": float(phase["duration_s"]),
                "delta_soc_obs": delta_soc,
                "soh_proxy_poh_phase": inferred_soh,
                "poh_soc_hat": poh_soc_hat,
                "phase_fit_abs_err": fit_abs_err,
                "phase_weight": weight,
                "median_power_kw": float(phase["median_power_kw"]),
                "median_ias_kts": float(phase["median_ias_kts"]),
                "median_agl_ft": float(phase["median_agl_ft"]),
            }
            phase_rows.append(row)
            per_batt_phase[batt_id].append(row)

    for batt_id, _ in batteries:
        rows = per_batt_phase[batt_id]
        valid = [
            r
            for r in rows
            if np.isfinite(r["soh_proxy_poh_phase"])
            and np.isfinite(r["phase_weight"])
            and float(r["phase_weight"]) > 0
        ]
        phase_count = len(valid)
        if phase_count > 0:
            w = np.array([float(r["phase_weight"]) for r in valid], dtype=float)
            soh_vals = np.array([float(r["soh_proxy_poh_phase"]) for r in valid], dtype=float)
            soh_flight = float(np.average(soh_vals, weights=w))
            fit_errs: list[float] = []
            fit_weights: list[float] = []
            for r in valid:
                delta_soc = float(r["delta_soc_obs"])
                phase_key = str(r["phase_key"])
                phase_soc_hat = interpolate_soc_from_soh(soh_flight, phase_key)
                fit_errs.append(abs(delta_soc - phase_soc_hat))
                fit_weights.append(float(max(r["phase_weight"], 1e-6)))
            mae = float(np.average(np.array(fit_errs, dtype=float), weights=np.array(fit_weights, dtype=float)))
            weight_sum = float(w.sum())
        else:
            soh_flight = np.nan
            mae = np.nan
            weight_sum = 0.0

        row = {
            "flight_id": flight_id,
            "source_folder": source_folder,
            "battery_id": batt_id,
            "soh_proxy_poh_flight": soh_flight,
            "phase_count_used": phase_count,
            "poh_fit_mae": mae,
            "phase_weight_sum": weight_sum,
        }
        for key, _, _ in POH_PHASE_TABLE:
            vals = [r["soh_proxy_poh_phase"] for r in rows if r["phase_key"] == key]
            row[f"soh_proxy_poh_phase_{key}"] = float(vals[0]) if vals else np.nan
        flight_rows.append(row)

    return phase_rows, flight_rows


def render_segment_plot(
    flight_id: int,
    df_active: pd.DataFrame,
    phases: list[dict[str, object]],
    out_path: Path,
) -> None:
    t_min = df_active["time_s"].to_numpy(dtype=float) / 60.0
    power = df_active["motor power"].fillna(0.0).to_numpy(dtype=float)
    agl_ft = df_active["agl_ft"].fillna(0.0).to_numpy(dtype=float)
    soc1 = pd.to_numeric(df_active["bat 1 soc"], errors="coerce").to_numpy(dtype=float)
    soc2 = pd.to_numeric(df_active["bat 2 soc"], errors="coerce").to_numpy(dtype=float)

    fig, axes = plt.subplots(3, 1, figsize=(15, 10), sharex=True)
    axes[0].plot(t_min, power, color="#1f77b4", linewidth=1.0)
    axes[0].set_ylabel("Motor power (kW)")
    axes[0].grid(alpha=0.2)

    axes[1].plot(t_min, agl_ft, color="#2ca02c", linewidth=1.0)
    axes[1].set_ylabel("AGL (ft)")
    axes[1].grid(alpha=0.2)

    axes[2].plot(t_min, soc1, color="#d62728", linewidth=1.1, label="bat 1 soc")
    axes[2].plot(t_min, soc2, color="#ff7f0e", linewidth=1.1, label="bat 2 soc")
    axes[2].set_ylabel("SOC (%)")
    axes[2].set_xlabel("Time in active flight window (min)")
    axes[2].grid(alpha=0.2)
    axes[2].legend(loc="best")

    for phase in phases:
        key = str(phase["phase_key"])
        color = PLOT_COLORS.get(key, "#aaaaaa")
        x0 = float(phase["start_time_s"]) / 60.0
        x1 = float(phase["end_time_s"]) / 60.0
        for ax in axes:
            ax.axvspan(x0, x1, color=color, alpha=0.18)
        axes[0].text(
            (x0 + x1) / 2.0,
            max(np.nanmax(power), 1.0) * 0.92,
            key.replace("_", "\n"),
            ha="center",
            va="top",
            fontsize=8,
        )

    fig.suptitle(f"Flight {flight_id} phase segmentation")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def render_inversion_ground_truth_plot(phase_df: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 8))

    for key, name, vals in POH_PHASE_TABLE:
        vals_np = np.array(vals, dtype=float)
        ax.plot(vals_np, SOH_GRID, color=PLOT_COLORS.get(key, None), linewidth=1.8, label=name)

    if not phase_df.empty:
        sub = phase_df[
            (phase_df["battery_id"] == "pack_avg")
            & phase_df["delta_soc_obs"].notna()
            & phase_df["soh_proxy_poh_phase"].notna()
        ].copy()
        if len(sub) > 5000:
            sub = sub.sample(n=5000, random_state=42)
        for key, g in sub.groupby("phase_key"):
            ax.scatter(
                g["delta_soc_obs"],
                g["soh_proxy_poh_phase"],
                s=12,
                alpha=0.25,
                color=PLOT_COLORS.get(str(key), "#444444"),
            )

    ax.set_xlabel("Observed phase SOC consumption (%)")
    ax.set_ylabel("Inferred SOH from POH inversion (%)")
    ax.set_title("POH inversion ground-truth chart (curves + inferred points)")
    ax.grid(alpha=0.25)

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, loc="upper right", fontsize=8)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def render_flight_soh_trend_plot(flight_df: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(14, 7))
    sub = flight_df[flight_df["battery_id"].isin(["1", "2", "pack_avg"])].copy()
    if sub.empty:
        return
    for batt_id, color in [("1", "#d62728"), ("2", "#1f77b4"), ("pack_avg", "#2ca02c")]:
        g = sub[sub["battery_id"] == batt_id].sort_values("flight_id")
        ax.plot(
            g["flight_id"],
            g["soh_proxy_poh_flight"],
            marker="o",
            markersize=2.5,
            linewidth=1.0,
            alpha=0.7,
            color=color,
            label=f"battery {batt_id}",
        )
    ax.set_xlabel("Flight ID")
    ax.set_ylabel("soh_proxy_poh_flight (%)")
    ax.set_title("Inferred flight-level SOH (POH proxy inversion)")
    ax.grid(alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def process_plane(cfg: Config) -> dict[str, object]:
    flights = discover_flights(cfg.raw_root, cfg.max_flights)
    summary: dict[str, object] = {
        "plane_id": cfg.plane_id,
        "raw_root": str(cfg.raw_root),
        "n_folders": len(flights),
        "n_processed": 0,
        "n_active": 0,
        "n_with_phases": 0,
        "n_errors": 0,
    }

    phase_rows_all: list[dict[str, object]] = []
    flight_rows_all: list[dict[str, object]] = []
    segment_rows: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    segments_for_plot: list[tuple[int, pd.DataFrame, list[dict[str, object]]]] = []

    for flight_id, folder in flights:
        summary["n_processed"] += 1
        main_csv = find_main_csv(folder)
        if main_csv is None:
            issues.append(
                {
                    "flight_id": flight_id,
                    "source_folder": folder.name,
                    "issue": "missing_main_csv",
                }
            )
            continue
        try:
            df = load_main_df(main_csv)
        except Exception as exc:
            summary["n_errors"] += 1
            issues.append(
                {
                    "flight_id": flight_id,
                    "source_folder": folder.name,
                    "issue": f"load_error:{type(exc).__name__}",
                }
            )
            continue

        active_run = pick_longest_active_run(df, cfg)
        if active_run is None:
            issues.append(
                {
                    "flight_id": flight_id,
                    "source_folder": folder.name,
                    "issue": "no_active_flight_window",
                }
            )
            continue

        summary["n_active"] += 1
        a0, a1 = active_run
        df_active = df.iloc[a0 : a1 + 1].copy().reset_index(drop=True)

        alt = (
            df_active["pressure_alt"]
            .ffill()
            .bfill()
            .fillna(0.0)
            .to_numpy(dtype=float)
        )
        baseline = float(np.nanpercentile(alt, 5))
        df_active["agl_ft"] = np.maximum(alt - baseline, 0.0)

        phases = segment_phases(df_active, cfg)
        if not phases:
            issues.append(
                {
                    "flight_id": flight_id,
                    "source_folder": folder.name,
                    "issue": "phase_segmentation_failed",
                }
            )
            continue

        summary["n_with_phases"] += 1
        p_rows, f_rows = compute_labels_for_flight(
            flight_id=flight_id,
            source_folder=folder.name,
            df_active=df_active,
            phases=phases,
        )
        phase_rows_all.extend(p_rows)
        flight_rows_all.extend(f_rows)

        for p in phases:
            segment_rows.append(
                {
                    "flight_id": flight_id,
                    "source_folder": folder.name,
                    "phase_key": p["phase_key"],
                    "phase_name": p["phase_name"],
                    "start_time_s": p["start_time_s"],
                    "end_time_s": p["end_time_s"],
                    "duration_s": p["duration_s"],
                    "median_power_kw": p["median_power_kw"],
                    "median_ias_kts": p["median_ias_kts"],
                    "median_agl_ft": p["median_agl_ft"],
                }
            )

        if len(segments_for_plot) < cfg.segment_plot_count:
            segments_for_plot.append((flight_id, df_active, phases))

    out_root = cfg.out_dir / f"plane_{cfg.plane_id}"
    out_root.mkdir(parents=True, exist_ok=True)

    phase_df = pd.DataFrame(phase_rows_all)
    flight_df = pd.DataFrame(flight_rows_all)
    segment_df = pd.DataFrame(segment_rows)
    issue_df = pd.DataFrame(issues)

    phase_path = out_root / "soh_proxy_poh_phase_labels.csv"
    flight_path = out_root / "soh_proxy_poh_flight_labels.csv"
    segment_path = out_root / "phase_segments.csv"
    issue_path = out_root / "pipeline_issues.csv"
    summary_path = out_root / "run_summary.csv"

    phase_df.to_csv(phase_path, index=False)
    flight_df.to_csv(flight_path, index=False)
    segment_df.to_csv(segment_path, index=False)
    issue_df.to_csv(issue_path, index=False)
    pd.DataFrame([summary]).to_csv(summary_path, index=False)

    plot_dir = out_root / "plots"
    for flight_id, df_active, phases in segments_for_plot:
        render_segment_plot(
            flight_id=flight_id,
            df_active=df_active,
            phases=phases,
            out_path=plot_dir / "segments" / f"flight_{flight_id}_segments.png",
        )

    render_inversion_ground_truth_plot(
        phase_df=phase_df,
        out_path=plot_dir / "poh_inversion_ground_truth.png",
    )
    render_flight_soh_trend_plot(
        flight_df=flight_df,
        out_path=plot_dir / "inferred_flight_soh_trend.png",
    )

    summary["output_dir"] = str(out_root)
    summary["phase_labels_csv"] = str(phase_path)
    summary["flight_labels_csv"] = str(flight_path)
    summary["segments_csv"] = str(segment_path)
    summary["issues_csv"] = str(issue_path)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Approach A POH-proxy SOH label builder. "
            "Segments active flights into POH-like phases, inverts the POH table, "
            "and exports phase/flight labels with QA plots."
        )
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/raw_csv/by_plane/166"),
        help="Input root containing extracted flight folders for a plane.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("ml_workspace/physics_soh/output/poh_proxy"),
        help="Base output directory.",
    )
    parser.add_argument(
        "--plane-id",
        type=str,
        default="166",
        help="Plane identifier used in output folder naming.",
    )
    parser.add_argument(
        "--max-flights",
        type=int,
        default=None,
        help="Optional cap on the number of flight folders processed.",
    )
    parser.add_argument(
        "--segment-plot-count",
        type=int,
        default=12,
        help="Number of per-flight segment plots to save for manual QA.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = Config(
        raw_root=args.raw_root,
        out_dir=args.out_dir,
        plane_id=args.plane_id,
        max_flights=args.max_flights,
        segment_plot_count=args.segment_plot_count,
    )
    summary = process_plane(cfg)
    print(pd.Series(summary).to_string())


if __name__ == "__main__":
    main()
