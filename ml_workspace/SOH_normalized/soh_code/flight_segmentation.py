from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


PHASE_NAME_BY_KEY = {
    "takeoff_initial_climb_300": "Take off and initial climb to 300 ft AGL",
    "climb_1000_vy_48kw": "1000 ft climb at Vy - 48 kW",
    "cruise_20kw_10min": "10 min cruise - 20 kW (69 KCAS)",
    "cruise_25kw_10min": "10 min cruise - 25 kW (78 KCAS)",
    "cruise_30kw_10min": "10 min cruise - 30 kW (86 KCAS)",
    "cruise_35kw_10min": "10 min cruise - 35 kW (92 KCAS)",
    "touch_and_go_climb_300": "Touch and go and climb to 300 ft AGL",
    "first_traffic_pattern": "Energy for the first traffic pattern",
    "generic_traffic_pattern": "Energy for a generic traffic pattern",
    "aborted_landing_climb_1000_64kw": "Aborted landing and climb to 1000 ft AGL at Vy - 64 kW",
}

CRUISE_KEYS = ["cruise_20kw_10min", "cruise_25kw_10min", "cruise_30kw_10min", "cruise_35kw_10min"]
CRUISE_BINS_KW = np.array([20.0, 25.0, 30.0, 35.0], dtype=float)


@dataclass
class SegmentationConfig:
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


def normalize_col(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def parse_flight_id(folder_name: str) -> int | None:
    m = re.match(r"^(?P<fid>\d+)-csv-", folder_name)
    if m:
        return int(m.group("fid"))
    m = re.match(r"^(?P<fid>\d+)", folder_name)
    return int(m.group("fid")) if m else None


def discover_flights(raw_root: Path, max_flights: int | None = None) -> list[tuple[int, Path]]:
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


def pick_active_window(df: pd.DataFrame, cfg: SegmentationConfig) -> tuple[int, int] | None:
    power = df["motor power"].fillna(0.0).to_numpy(dtype=float)
    ias = df["ias"].fillna(0.0).to_numpy(dtype=float)
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
    win = (int(idx[0]), int(idx[-1]))
    if run_duration_seconds(t_s, win[0], win[1]) < cfg.min_active_seconds:
        return None
    return win


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
            "phase_name": PHASE_NAME_BY_KEY[key],
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


def segment_phases(df_active: pd.DataFrame, cfg: SegmentationConfig) -> list[dict[str, object]]:
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


def segment_flight_dataframe(df: pd.DataFrame, cfg: SegmentationConfig) -> tuple[pd.DataFrame | None, list[dict[str, object]], str | None]:
    active_run = pick_active_window(df, cfg)
    if active_run is None:
        return None, [], "no_active_flight_window"

    a0, a1 = active_run
    df_active = df.iloc[a0 : a1 + 1].copy().reset_index(drop=True)
    alt = df_active["pressure_alt"].ffill().bfill().fillna(0.0).to_numpy(dtype=float)
    baseline = float(np.nanpercentile(alt, 5))
    df_active["agl_ft"] = np.maximum(alt - baseline, 0.0)

    phases = segment_phases(df_active, cfg)
    if not phases:
        return df_active, [], "phase_segmentation_failed"
    return df_active, phases, None


def segment_plane(
    raw_root: Path,
    cfg: SegmentationConfig,
    max_flights: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    segments: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    summary = {"n_folders": 0, "n_processed": 0, "n_with_phases": 0, "n_errors": 0}

    flights = discover_flights(raw_root, max_flights=max_flights)
    summary["n_folders"] = len(flights)

    for flight_id, folder in flights:
        summary["n_processed"] += 1
        main_csv = find_main_csv(folder)
        if main_csv is None:
            issues.append({"flight_id": flight_id, "source_folder": folder.name, "issue": "missing_main_csv"})
            continue
        try:
            df = load_main_df(main_csv)
            _, phases, issue = segment_flight_dataframe(df, cfg)
        except Exception as exc:
            summary["n_errors"] += 1
            issues.append(
                {
                    "flight_id": flight_id,
                    "source_folder": folder.name,
                    "issue": f"load_or_segment_error:{type(exc).__name__}",
                }
            )
            continue
        if issue is not None:
            issues.append({"flight_id": flight_id, "source_folder": folder.name, "issue": issue})
            continue
        summary["n_with_phases"] += 1
        for p in phases:
            segments.append(
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

    return pd.DataFrame(segments), pd.DataFrame(issues), pd.DataFrame([summary])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reusable flight segmentation module for POH-style phases.")
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/raw_csv/by_plane/166"),
        help="Input root containing extracted flight folders for a plane.",
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=Path("ml_workspace/SOH_normalized/output/segments/plane_166_phase_segments.csv"),
        help="Output CSV for segmented phases.",
    )
    parser.add_argument(
        "--issues-csv",
        type=Path,
        default=Path("ml_workspace/SOH_normalized/output/segments/plane_166_segmentation_issues.csv"),
        help="Output CSV for segmentation issues.",
    )
    parser.add_argument(
        "--summary-csv",
        type=Path,
        default=Path("ml_workspace/SOH_normalized/output/segments/plane_166_segmentation_summary.csv"),
        help="Output CSV for run summary.",
    )
    parser.add_argument("--max-flights", type=int, default=None, help="Optional cap on number of folders.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = SegmentationConfig()
    seg_df, issues_df, summary_df = segment_plane(
        raw_root=args.raw_root,
        cfg=cfg,
        max_flights=args.max_flights,
    )
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    args.issues_csv.parent.mkdir(parents=True, exist_ok=True)
    args.summary_csv.parent.mkdir(parents=True, exist_ok=True)
    seg_df.to_csv(args.out_csv, index=False)
    issues_df.to_csv(args.issues_csv, index=False)
    summary_df.to_csv(args.summary_csv, index=False)
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
