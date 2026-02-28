from __future__ import annotations

import argparse
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError:
    plt = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "data" / "event_manifest.parquet"
DEFAULT_TIMESERIES_PATH = PROJECT_ROOT / "data" / "event_timeseries.parquet"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "ml_workspace" / "battery_inference" / "output"

CAPACITY_119_AH = 29.0
CAPACITY_124_AH = 33.0
MIDPOINT_AH = (CAPACITY_119_AH + CAPACITY_124_AH) / 2.0
MAX_VOLTAGE_119 = 402.0
MAX_VOLTAGE_124 = 398.0


@dataclass
class Config:
    manifest_path: Path = DEFAULT_MANIFEST_PATH
    timeseries_path: Path = DEFAULT_TIMESERIES_PATH
    output_root: Path = DEFAULT_OUTPUT_ROOT
    plane_id: str = "166"
    min_rows_per_event: int = 1000
    min_soc_span_pct: float = 20.0
    min_monotonic_frac: float = 0.95
    current_charge_min_a: float = -40.0
    current_charge_max_a: float = 5.0
    voltage_min_v: float = 300.0
    voltage_max_v: float = 410.0
    temp_min_c: float = 0.0
    temp_max_c: float = 45.0
    voltage_top_soc_threshold: float = 95.0
    low_sample_confidence_cutoff: int = 20
    battery_consistency_tolerance_ah: float = 1.5
    spread_penalty_iqr_ah: float = 2.0


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Infer the plane-level battery type from charging telemetry.")
    parser.add_argument("--plane-id", default="166", help="Plane ID to analyze.")
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH), help="Path to event_manifest.parquet.")
    parser.add_argument("--timeseries-path", default=str(DEFAULT_TIMESERIES_PATH), help="Path to event_timeseries.parquet.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Directory for output artifacts.")
    ns = parser.parse_args()
    return Config(
        plane_id=str(ns.plane_id),
        manifest_path=Path(ns.manifest_path),
        timeseries_path=Path(ns.timeseries_path),
        output_root=Path(ns.output_root),
    )


def _map_pack_columns(pack_id: int) -> dict[str, str]:
    if pack_id not in (1, 2):
        raise ValueError(f"unsupported pack_id: {pack_id}")
    p = str(pack_id)
    return {
        "time_ms": "time_ms",
        "current_a": f" bat {p} current",
        "voltage_v": f" bat {p} voltage",
        "soc_pct": f" bat {p} soc",
        "cap_est_raw": f" bat {p} cap est",
        "temp_c": f" bat {p} avg cell temp",
    }


def _load_pack_rows(dataset: ds.Dataset, manifest: pd.DataFrame, plane_id: str, pack_id: int) -> pd.DataFrame:
    col_map = _map_pack_columns(pack_id)
    cols = [
        "flight_id",
        "plane_id",
        "event_datetime",
        "is_charging_event",
        "source_csv_kind",
        "source_pack_id",
        "time_ms",
        col_map["current_a"],
        col_map["voltage_v"],
        col_map["soc_pct"],
        col_map["cap_est_raw"],
        col_map["temp_c"],
    ]
    filter_expr = (
        (ds.field("plane_id") == str(plane_id))
        & (ds.field("is_charging_event") == 1)
        & (ds.field("source_csv_kind") == "aux")
        & (ds.field("source_pack_id") == pack_id)
    )
    table = dataset.to_table(columns=cols, filter=filter_expr)
    df = table.to_pandas()
    rename_map = {v: k for k, v in col_map.items()}
    df = df.rename(columns=rename_map)
    keep_cols = [
        "flight_id",
        "plane_id",
        "event_datetime",
        "is_charging_event",
        "source_csv_kind",
        "source_pack_id",
        "time_ms",
        "current_a",
        "voltage_v",
        "soc_pct",
        "cap_est_raw",
        "temp_c",
    ]
    df = df[keep_cols].copy()
    df["battery_id"] = pack_id
    df = df.merge(
        manifest[["flight_id", "event_datetime"]].drop_duplicates("flight_id"),
        on=["flight_id", "event_datetime"],
        how="left",
    )
    return df


def load_charge_events(manifest_path: str | Path, timeseries_path: str | Path, plane_id: str) -> pd.DataFrame:
    manifest = pd.read_parquet(manifest_path, columns=["flight_id", "plane_id", "event_datetime", "is_charging_event"])
    manifest = manifest[(manifest["plane_id"].astype(str) == str(plane_id)) & (manifest["is_charging_event"] == 1)].copy()
    manifest["event_datetime"] = pd.to_datetime(manifest["event_datetime"], errors="coerce")

    dataset = ds.dataset(str(timeseries_path), format="parquet")
    frames = [_load_pack_rows(dataset, manifest, str(plane_id), pack_id) for pack_id in (1, 2)]
    out = pd.concat(frames, ignore_index=True)
    out["event_datetime"] = pd.to_datetime(out["event_datetime"], errors="coerce")
    out = out.sort_values(["flight_id", "battery_id", "time_ms"]).reset_index(drop=True)
    return out


def clean_charge_event(df: pd.DataFrame, cfg: Config | None = None) -> pd.DataFrame:
    cfg = cfg or Config()
    work = df.sort_values("time_ms").drop_duplicates(subset=["time_ms"], keep="first").copy()

    valid = (
        work["time_ms"].notna()
        & work["current_a"].between(cfg.current_charge_min_a, cfg.current_charge_max_a)
        & work["voltage_v"].between(cfg.voltage_min_v, cfg.voltage_max_v)
        & work["soc_pct"].between(0.0, 100.0)
        & work["temp_c"].between(cfg.temp_min_c, cfg.temp_max_c)
    )
    valid &= (work["voltage_v"] > 0.0) & (work["soc_pct"] > 0.0)

    if not valid.any():
        return work.iloc[0:0].copy()

    first_idx = int(np.flatnonzero(valid.to_numpy())[0])
    last_idx = int(np.flatnonzero(valid.to_numpy())[-1])
    trimmed = work.iloc[first_idx : last_idx + 1].copy()
    trimmed = trimmed.loc[valid.iloc[first_idx : last_idx + 1].to_numpy()].copy()
    trimmed = trimmed.sort_values("time_ms").reset_index(drop=True)

    if trimmed.empty:
        return trimmed

    trimmed["dt_s"] = trimmed["time_ms"].diff().div(1000.0)
    trimmed = trimmed.loc[trimmed["dt_s"].fillna(0.0) >= 0.0].copy()
    trimmed["dt_s"] = trimmed["dt_s"].fillna(0.0)
    trimmed["soc_diff"] = trimmed["soc_pct"].diff()
    trimmed["charge_current_a"] = (-trimmed["current_a"]).clip(lower=0.0)
    trimmed["dq_ah_step"] = trimmed["charge_current_a"] * trimmed["dt_s"] / 3600.0
    trimmed["q_ah"] = trimmed["dq_ah_step"].cumsum()
    return trimmed.reset_index(drop=True)


def _select_soc_window(soc_min: float, soc_max: float) -> tuple[float, float, str] | None:
    windows = [
        (40.0, 90.0, "40-90"),
        (30.0, 80.0, "30-80"),
        (50.0, 90.0, "50-90"),
    ]
    for lo, hi, label in windows:
        if soc_min <= lo and soc_max >= hi:
            return lo, hi, label
    return None


def _interp_q_at_soc(soc: np.ndarray, q_ah: np.ndarray, target_soc: float) -> float:
    order = np.argsort(soc, kind="mergesort")
    soc_sorted = soc[order]
    q_sorted = q_ah[order]
    unique_soc, unique_idx = np.unique(soc_sorted, return_index=True)
    q_unique = q_sorted[unique_idx]
    if len(unique_soc) < 2:
        raise ValueError("not_enough_unique_soc_points")
    return float(np.interp(target_soc, unique_soc, q_unique))


def estimate_event_capacity(df: pd.DataFrame, cfg: Config | None = None) -> dict[str, float | int | str] | None:
    cfg = cfg or Config()
    if df.empty or len(df) < cfg.min_rows_per_event:
        return None

    soc_diff = df["soc_pct"].diff().dropna()
    monotonic_frac = float((soc_diff >= -0.5).mean()) if not soc_diff.empty else 0.0
    soc_start = float(df["soc_pct"].iloc[0])
    soc_end = float(df["soc_pct"].iloc[-1])
    soc_span = soc_end - soc_start

    if monotonic_frac < cfg.min_monotonic_frac or soc_span < cfg.min_soc_span_pct:
        return None

    window = _select_soc_window(float(df["soc_pct"].min()), float(df["soc_pct"].max()))
    if window is None:
        return None
    soc_lo, soc_hi, label = window

    q_lo = _interp_q_at_soc(df["soc_pct"].to_numpy(dtype=float), df["q_ah"].to_numpy(dtype=float), soc_lo)
    q_hi = _interp_q_at_soc(df["soc_pct"].to_numpy(dtype=float), df["q_ah"].to_numpy(dtype=float), soc_hi)
    delivered_ah = q_hi - q_lo
    soc_fraction = (soc_hi - soc_lo) / 100.0
    if soc_fraction <= 0.0 or delivered_ah <= 0.0:
        return None

    return {
        "flight_id": int(df["flight_id"].iloc[0]),
        "battery_id": int(df["battery_id"].iloc[0]),
        "event_datetime": pd.Timestamp(df["event_datetime"].iloc[0]).isoformat(),
        "soc_start": soc_start,
        "soc_end": soc_end,
        "soc_span": soc_span,
        "soc_window_used": label,
        "delivered_ah": float(delivered_ah),
        "capacity_est_ah": float(delivered_ah / soc_fraction),
        "cap_est_raw_median": float(df["cap_est_raw"].median()),
        "v_max": float(df["voltage_v"].max()),
        "v_p99": float(df["voltage_v"].quantile(0.99)),
        "rows_used": int(len(df)),
        "monotonic_soc_frac": monotonic_frac,
    }


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def infer_plane_battery_type(event_summary: pd.DataFrame, cfg: Config | None = None) -> dict[str, object]:
    cfg = cfg or Config()
    if event_summary.empty:
        return {
            "plane_id": cfg.plane_id,
            "battery_type_inferred": "unknown",
            "capacity_est_median_ah": None,
            "capacity_est_iqr_ah": None,
            "capacity_est_mad_ah": None,
            "n_event_battery_samples": 0,
            "battery_1_capacity_median_ah": None,
            "battery_2_capacity_median_ah": None,
            "vmax_median": None,
            "vp99_median": None,
            "confidence": 0.0,
            "decision_basis": "insufficient_data",
            "notes": "No valid event-battery segments survived QC.",
        }

    cap = event_summary["capacity_est_ah"].astype(float)
    cap_median = float(cap.median())
    cap_q1 = float(cap.quantile(0.25))
    cap_q3 = float(cap.quantile(0.75))
    cap_iqr = cap_q3 - cap_q1
    cap_mad = float(np.median(np.abs(cap - cap_median)))

    battery_medians = event_summary.groupby("battery_id")["capacity_est_ah"].median()
    b1_median = float(battery_medians.get(1, np.nan)) if 1 in battery_medians.index else None
    b2_median = float(battery_medians.get(2, np.nan)) if 2 in battery_medians.index else None

    top = event_summary[event_summary["soc_end"] >= cfg.voltage_top_soc_threshold].copy()
    vmax_median = float(top["v_max"].median()) if not top.empty else None
    vp99_median = float(top["v_p99"].median()) if not top.empty else None

    dist_119 = abs(cap_median - CAPACITY_119_AH)
    dist_124 = abs(cap_median - CAPACITY_124_AH)
    inferred = "PB345V119E-L" if dist_119 <= dist_124 else "PB345V124E-L"

    notes: list[str] = []
    capacity_margin = abs(cap_median - MIDPOINT_AH)
    confidence = 0.55 + 0.35 * _clip01(capacity_margin / 2.0)
    confidence *= 0.7 + 0.3 * _clip01(len(event_summary) / 40.0)

    if cap_iqr > cfg.spread_penalty_iqr_ah:
        confidence *= 0.8
        notes.append(f"capacity_iqr_high={cap_iqr:.2f}Ah")
    if len(event_summary) < cfg.low_sample_confidence_cutoff:
        confidence *= 0.7
        notes.append(f"low_sample_count={len(event_summary)}")
    if b1_median is not None and b2_median is not None and abs(b1_median - b2_median) > cfg.battery_consistency_tolerance_ah:
        confidence *= 0.8
        notes.append(f"battery_median_gap={abs(b1_median - b2_median):.2f}Ah")

    decision_basis = "capacity_primary_voltage_neutral"
    if vmax_median is not None:
        if inferred == "PB345V119E-L":
            if vmax_median >= 400.5:
                confidence = min(1.0, confidence + 0.08)
                decision_basis = "capacity_primary_voltage_supporting"
            elif vmax_median <= 399.0:
                confidence *= 0.9
                notes.append(f"voltage_crosscheck_low={vmax_median:.2f}V")
        else:
            if vmax_median <= 399.0:
                confidence = min(1.0, confidence + 0.08)
                decision_basis = "capacity_primary_voltage_supporting"
            elif vmax_median >= 400.5:
                confidence *= 0.9
                notes.append(f"voltage_crosscheck_high={vmax_median:.2f}V")
    else:
        notes.append("no_high_soc_voltage_crosscheck")

    if abs(dist_119 - dist_124) < 0.5:
        decision_basis = "capacity_ambiguous"
        confidence *= 0.75
        notes.append("capacity_near_midpoint")

    return {
        "plane_id": cfg.plane_id,
        "battery_type_inferred": inferred,
        "capacity_est_median_ah": cap_median,
        "capacity_est_iqr_ah": cap_iqr,
        "capacity_est_mad_ah": cap_mad,
        "n_event_battery_samples": int(len(event_summary)),
        "battery_1_capacity_median_ah": b1_median,
        "battery_2_capacity_median_ah": b2_median,
        "vmax_median": vmax_median,
        "vp99_median": vp99_median,
        "distance_to_29ah": dist_119,
        "distance_to_33ah": dist_124,
        "confidence": _clip01(confidence),
        "decision_basis": decision_basis,
        "notes": "; ".join(notes) if notes else "capacity estimate and voltage cross-check are aligned.",
    }


def _run_validation_checks(cfg: Config) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []

    time_s = np.arange(0.0, 1800.0, 1.0)
    current_a = np.full_like(time_s, -20.0, dtype=float)
    q_ah = np.cumsum(np.r_[0.0, (-current_a[1:]) / 3600.0])
    soc_pct = 40.0 + 50.0 * (time_s / time_s[-1])
    synthetic = pd.DataFrame(
        {
            "flight_id": 1,
            "battery_id": 1,
            "event_datetime": pd.Timestamp("2024-01-01T00:00:00"),
            "time_ms": time_s * 1000.0,
            "current_a": current_a,
            "voltage_v": 360.0 + 40.0 * (time_s / time_s[-1]),
            "soc_pct": soc_pct,
            "cap_est_raw": 0.0,
            "temp_c": 20.0,
            "q_ah": q_ah,
        }
    )
    estimated = estimate_event_capacity(synthetic, cfg)
    checks.append(
        {
            "name": "synthetic_capacity_recovery",
            "passed": estimated is not None and abs(float(estimated["capacity_est_ah"]) - 20.0) < 0.1,
        }
    )

    dirty = pd.DataFrame(
        {
            "flight_id": [1, 1, 1, 1],
            "battery_id": [1, 1, 1, 1],
            "event_datetime": [pd.Timestamp("2024-01-01")] * 4,
            "time_ms": [0.0, 1000.0, 2000.0, 3000.0],
            "current_a": [0.0, -20.0, -20.0, -20.0],
            "voltage_v": [0.0, 350.0, 351.0, 352.0],
            "soc_pct": [0.0, 40.0, 41.0, 42.0],
            "cap_est_raw": [0.0, 0.0, 0.0, 0.0],
            "temp_c": [0.0, 20.0, 20.0, 20.0],
        }
    )
    cleaned = clean_charge_event(dirty, cfg)
    checks.append(
        {
            "name": "startup_zero_trim",
            "passed": not cleaned.empty and float(cleaned["time_ms"].iloc[0]) == 1000.0,
        }
    )

    ambiguous = pd.DataFrame(
        {
            "capacity_est_ah": [28.8, 29.2, 29.1, 28.9, 29.0, 29.3],
            "battery_id": [1, 1, 2, 2, 1, 2],
            "soc_end": [99, 99, 99, 99, 99, 99],
            "v_max": [401.9, 402.0, 401.8, 402.1, 401.9, 402.0],
            "v_p99": [401.6, 401.8, 401.7, 401.8, 401.7, 401.8],
        }
    )
    inferred_119 = infer_plane_battery_type(ambiguous, cfg)
    checks.append({"name": "decision_near_29ah", "passed": inferred_119["battery_type_inferred"] == "PB345V119E-L"})

    near_33 = ambiguous.copy()
    near_33["capacity_est_ah"] = [32.8, 33.1, 33.0, 33.2, 32.9, 33.0]
    near_33["v_max"] = [398.1, 398.0, 398.2, 398.0, 398.1, 398.0]
    near_33["v_p99"] = [397.8, 397.9, 397.8, 397.9, 397.8, 397.9]
    inferred_124 = infer_plane_battery_type(near_33, cfg)
    checks.append({"name": "decision_near_33ah", "passed": inferred_124["battery_type_inferred"] == "PB345V124E-L"})
    return checks


def _draw_rect(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
    h, w, _ = img.shape
    x0 = max(0, min(w, x0))
    x1 = max(0, min(w, x1))
    y0 = max(0, min(h, y0))
    y1 = max(0, min(h, y1))
    if x1 <= x0 or y1 <= y0:
        return
    img[y0:y1, x0:x1] = color


def _draw_vline(img: np.ndarray, x: int, y0: int, y1: int, color: tuple[int, int, int], width: int = 1) -> None:
    _draw_rect(img, x - width // 2, y0, x + width // 2 + 1, y1, color)


def _draw_hline(img: np.ndarray, x0: int, x1: int, y: int, color: tuple[int, int, int], width: int = 1) -> None:
    _draw_rect(img, x0, y - width // 2, x1, y + width // 2 + 1, color)


def _draw_point(img: np.ndarray, x: int, y: int, color: tuple[int, int, int], size: int = 2) -> None:
    _draw_rect(img, x - size, y - size, x + size + 1, y + size + 1, color)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _write_png(path: Path, img: np.ndarray) -> None:
    if img.dtype != np.uint8:
        img = img.astype(np.uint8)
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))
    data = zlib.compress(raw, level=9)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += _png_chunk(b"IDAT", data)
    png += _png_chunk(b"IEND", b"")
    path.write_bytes(png)


def _render_diagnostics_fallback(summary: pd.DataFrame, result: dict[str, object], out_path: Path) -> None:
    width = 1500
    height = 480
    img = np.full((height, width, 3), 248, dtype=np.uint8)
    panels = [(30, 20, 490, 430), (520, 20, 980, 430), (1010, 20, 1470, 430)]
    axis_color = (40, 40, 40)

    for x0, y0, x1, y1 in panels:
        _draw_rect(img, x0, y0, x1, y1, (255, 255, 255))
        _draw_rect(img, x0, y0, x1, y0 + 1, (210, 210, 210))
        _draw_rect(img, x0, y1 - 1, x1, y1, (210, 210, 210))
        _draw_rect(img, x0, y0, x0 + 1, y1, (210, 210, 210))
        _draw_rect(img, x1 - 1, y0, x1, y1, (210, 210, 210))
        _draw_hline(img, x0 + 40, x1 - 20, y1 - 35, axis_color)
        _draw_vline(img, x0 + 40, y0 + 20, y1 - 35, axis_color)

    cap = summary["capacity_est_ah"].to_numpy(dtype=float)
    cap_min = float(np.floor(cap.min()))
    cap_max = float(np.ceil(cap.max()))
    bins = np.linspace(cap_min, cap_max, 24)
    counts, edges = np.histogram(cap, bins=bins)
    p0 = panels[0]
    plot_h = (p0[3] - 35) - (p0[1] + 20)
    plot_w = (p0[2] - 20) - (p0[0] + 40)
    max_count = max(int(counts.max()), 1)
    bar_w = max(1, int(plot_w / len(counts)))
    for i, count in enumerate(counts):
        x = p0[0] + 40 + i * bar_w
        h = int((count / max_count) * (plot_h - 10))
        _draw_rect(img, x, p0[3] - 35 - h, x + bar_w - 1, p0[3] - 35, (47, 93, 98))
    for value, color in [
        (CAPACITY_119_AH, (209, 73, 91)),
        (CAPACITY_124_AH, (0, 121, 140)),
        (float(result["capacity_est_median_ah"]), (34, 34, 34)),
    ]:
        xp = p0[0] + 40 + int(((value - cap_min) / max(cap_max - cap_min, 1e-6)) * plot_w)
        _draw_vline(img, xp, p0[1] + 20, p0[3] - 35, color, width=2)

    p1 = panels[1]
    dates = pd.to_datetime(summary["event_datetime"], errors="coerce").astype("int64").to_numpy()
    yvals = cap
    xmin, xmax = int(np.nanmin(dates)), int(np.nanmax(dates))
    ymin, ymax = float(np.nanmin(yvals)), float(np.nanmax(yvals))
    for _, row in summary.iterrows():
        xval = int(pd.Timestamp(row["event_datetime"]).value)
        yval = float(row["capacity_est_ah"])
        xp = p1[0] + 40 + int(((xval - xmin) / max(xmax - xmin, 1)) * plot_w)
        yp = p1[3] - 35 - int(((yval - ymin) / max(ymax - ymin, 1e-6)) * plot_h)
        color = (34, 110, 180) if int(row["battery_id"]) == 1 else (220, 120, 30)
        _draw_point(img, xp, yp, color, size=2)

    top = summary[summary["soc_end"] >= 95].copy()
    p2 = panels[2]
    if not top.empty:
        vmax = top["v_max"].to_numpy(dtype=float)
        vmin = float(np.floor(vmax.min()))
        vmax_lim = float(np.ceil(vmax.max()))
        v_bins = np.linspace(vmin, vmax_lim, 20)
        v_counts, _ = np.histogram(vmax, bins=v_bins)
        v_bar_w = max(1, int(plot_w / len(v_counts)))
        v_count_max = max(int(v_counts.max()), 1)
        for i, count in enumerate(v_counts):
            x = p2[0] + 40 + i * v_bar_w
            h = int((count / v_count_max) * (plot_h - 10))
            _draw_rect(img, x, p2[3] - 35 - h, x + v_bar_w - 1, p2[3] - 35, (237, 174, 73))
        for value, color in [
            (MAX_VOLTAGE_124, (0, 121, 140)),
            (MAX_VOLTAGE_119, (209, 73, 91)),
            (float(result["vmax_median"]), (34, 34, 34)),
        ]:
            xp = p2[0] + 40 + int(((value - vmin) / max(vmax_lim - vmin, 1e-6)) * plot_w)
            _draw_vline(img, xp, p2[1] + 20, p2[3] - 35, color, width=2)

    _write_png(out_path, img)


def _render_diagnostics(summary: pd.DataFrame, result: dict[str, object], out_path: Path) -> None:
    if plt is None:
        _render_diagnostics_fallback(summary, result, out_path)
        return
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))

    axes[0].hist(summary["capacity_est_ah"], bins=30, color="#2f5d62", edgecolor="white")
    axes[0].axvline(CAPACITY_119_AH, color="#d1495b", lw=1.5, linestyle="--")
    axes[0].axvline(CAPACITY_124_AH, color="#00798c", lw=1.5, linestyle="--")
    axes[0].axvline(float(result["capacity_est_median_ah"]), color="#222222", lw=2.0)
    axes[0].set_title("Estimated Capacity")
    axes[0].set_xlabel("Ah")

    axes[1].scatter(summary["event_datetime"], summary["capacity_est_ah"], s=10, alpha=0.6, c=summary["battery_id"])
    axes[1].set_title("Capacity Over Time")
    axes[1].set_xlabel("Event Time")
    axes[1].tick_params(axis="x", rotation=30)

    top = summary[summary["soc_end"] >= 95].copy()
    if not top.empty:
        axes[2].hist(top["v_max"], bins=20, color="#edae49", edgecolor="white")
        axes[2].axvline(MAX_VOLTAGE_124, color="#00798c", lw=1.5, linestyle="--")
        axes[2].axvline(MAX_VOLTAGE_119, color="#d1495b", lw=1.5, linestyle="--")
        if result["vmax_median"] is not None:
            axes[2].axvline(float(result["vmax_median"]), color="#222222", lw=2.0)
        axes[2].set_xlabel("V")
    else:
        axes[2].text(0.5, 0.5, "No high-SOC charge events", ha="center", va="center", transform=axes[2].transAxes)
    axes[2].set_title("Top-of-Charge Voltage")

    fig.suptitle(
        f"Plane {result['plane_id']} inferred as {result['battery_type_inferred']} "
        f"(confidence {float(result['confidence']):.2f})"
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    cfg = parse_args()
    out_dir = cfg.output_root / f"plane_{cfg.plane_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    checks = _run_validation_checks(cfg)

    raw = load_charge_events(cfg.manifest_path, cfg.timeseries_path, cfg.plane_id)
    summaries: list[dict[str, object]] = []

    for (_, _), group in raw.groupby(["flight_id", "battery_id"], sort=True):
        cleaned = clean_charge_event(group, cfg)
        summary = estimate_event_capacity(cleaned, cfg)
        if summary is not None:
            summaries.append(summary)

    summary_df = pd.DataFrame(summaries)
    if not summary_df.empty:
        summary_df["event_datetime"] = pd.to_datetime(summary_df["event_datetime"], errors="coerce")
        summary_df = summary_df.sort_values(["event_datetime", "flight_id", "battery_id"]).reset_index(drop=True)

    result = infer_plane_battery_type(summary_df, cfg)
    result["validation_checks"] = checks
    result["n_charging_event_rows_loaded"] = int(len(raw))
    result["n_unique_charging_events"] = int(raw["flight_id"].nunique()) if not raw.empty else 0
    result["n_valid_event_battery_segments"] = int(len(summary_df))
    result["diagnostic_plot_generated"] = False

    summary_path = out_dir / "charge_event_capacity_summary.csv"
    result_path = out_dir / "plane_battery_inference.json"
    plot_path = out_dir / "diagnostic_plots.png"

    if not summary_df.empty:
        summary_df.to_csv(summary_path, index=False)
        _render_diagnostics(summary_df, result, plot_path)
        result["diagnostic_plot_generated"] = plot_path.exists()
    else:
        pd.DataFrame(
            columns=[
                "flight_id",
                "battery_id",
                "event_datetime",
                "soc_start",
                "soc_end",
                "soc_span",
                "soc_window_used",
                "delivered_ah",
                "capacity_est_ah",
                "cap_est_raw_median",
                "v_max",
                "v_p99",
                "rows_used",
                "monotonic_soc_frac",
            ]
        ).to_csv(summary_path, index=False)

    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
