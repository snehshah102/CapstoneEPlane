from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from flight_segmentation import (
    SegmentationConfig,
    discover_flights,
    find_main_csv,
    segment_flight_dataframe,
)


@dataclass
class Config:
    raw_root: Path
    out_dir: Path
    plane_id: str
    max_flights: int | None = None
    max_soh_jump_pct_per_min: float = 4.0
    max_soh_jump_abs: float = 1.5
    jump_window_max_s: float = 90.0
    min_model_rows: int = 1200
    min_label_rows: int = 60
    min_label_rows_preferred_regime: int = 20
    huber_k: float = 1.5
    huber_iters: int = 20
    plot_sample_points: int = 8000
    cap_est_min_ah: float = 2000.0
    cap_est_max_ah: float = 20000.0
    max_abs_kalman_gap: float = 20.0
    max_volt_spread_v: float = 50.0
    max_temp_spread_c: float = 25.0
    max_c_rate: float = 8.0
    feature_clip_lower_q: float = 0.01
    feature_clip_upper_q: float = 0.99
    clean_jump_abs: float = 12.0
    clean_jump_mad_mult: float = 4.0
    clean_jump_raw_confirm_abs: float = 8.0
    clean_feature_outlier_ratio_jump: float = 0.15
    clean_roll_window: int = 5
    clean_delta_cap_abs: float = 6.0
    clean_transient_pair_abs: float = 12.0


def build_flight_index_lookup(flights: list[tuple[int, Path]]) -> pd.DataFrame:
    rows = []
    for i, (flight_id, folder) in enumerate(flights, start=1):
        rows.append(
            {
                "flight_index": i,
                "flight_id": int(flight_id),
                "source_folder": folder.name,
            }
        )
    return pd.DataFrame(rows)


def normalize_col(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def pack_csv_path(flight_dir: Path, pack_id: int) -> Path | None:
    wanted = f"_{pack_id}.csv"
    for p in sorted(flight_dir.glob("*.csv")):
        if p.name.lower().endswith(wanted):
            return p
    return None


def load_main_for_norm(path: Path) -> pd.DataFrame:
    needed = {
        "time(ms)",
        "bat 1 soc",
        "bat 2 soc",
        "bat 1 current",
        "bat 2 current",
        "motor power",
        "oat",
        "ias",
        "pressure_alt",
    }
    df = pd.read_csv(
        path,
        skipinitialspace=True,
        low_memory=False,
        usecols=lambda c: normalize_col(c) in needed,
    )
    df = df.rename(columns={c: normalize_col(c) for c in df.columns})
    for col in needed:
        if col not in df.columns:
            df[col] = np.nan
    for col in needed:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time(ms)"]).sort_values("time(ms)").reset_index(drop=True)
    df = df.loc[df["time(ms)"].diff().fillna(1.0) > 0].copy()
    if df.empty:
        raise ValueError("empty_or_invalid_main")
    t0 = float(df["time(ms)"].iloc[0])
    df["time_s"] = (df["time(ms)"] - t0) / 1000.0
    return df


def load_pack_df(path: Path, pack_id: int) -> pd.DataFrame:
    p = str(pack_id)
    needed = {
        "time(ms)",
        f"bat {p} soh",
        f"bat {p} kalman soc",
        f"bat {p} coulomb soc out",
        f"bat {p} cap est",
        f"bat {p} min cell volt",
        f"bat {p} max cell volt",
        f"bat {p} min cell temp",
        f"bat {p} max cell temp",
        f"bat {p} avg cell temp",
        f"bat {p} cell flg rst coulomb",
        f"bat {p} cell flg new est batt cap",
    }
    df = pd.read_csv(
        path,
        skipinitialspace=True,
        low_memory=False,
        usecols=lambda c: normalize_col(c) in needed,
    )
    df = df.rename(columns={c: normalize_col(c) for c in df.columns})
    for col in needed:
        if col not in df.columns:
            df[col] = np.nan
    for col in needed:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time(ms)"]).sort_values("time(ms)").reset_index(drop=True)
    df = df.loc[df["time(ms)"].diff().fillna(1.0) > 0].copy()
    return df


def phase_to_regime(phase_key: str) -> str:
    if phase_key.startswith("cruise_"):
        return "cruise"
    if "traffic_pattern" in phase_key:
        return "pattern"
    if phase_key in {
        "takeoff_initial_climb_300",
        "climb_1000_vy_48kw",
        "touch_and_go_climb_300",
        "aborted_landing_climb_1000_64kw",
    }:
        return "climb"
    return "other"


def build_regime_series(df_active: pd.DataFrame, phases: list[dict[str, object]]) -> pd.Series:
    regime = pd.Series(["other"] * len(df_active), index=df_active.index, dtype="object")
    for p in phases:
        s = int(p["start_idx"])
        e = int(p["end_idx"])
        regime_name = phase_to_regime(str(p["phase_key"]))
        regime.iloc[s : e + 1] = regime_name
    return regime


def robust_huber_fit(
    x_raw: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    huber_k: float,
    iters: int,
) -> dict[str, object]:
    med = np.nanmedian(x_raw, axis=0)
    mad = np.nanmedian(np.abs(x_raw - med), axis=0)
    scale = 1.4826 * mad
    scale[~np.isfinite(scale) | (scale < 1e-6)] = 1.0
    x = (x_raw - med) / scale
    n = x.shape[0]
    x_aug = np.column_stack([np.ones(n), x])

    beta, *_ = np.linalg.lstsq(x_aug, y, rcond=None)
    for _ in range(iters):
        resid = y - x_aug @ beta
        s = 1.4826 * np.nanmedian(np.abs(resid))
        if not np.isfinite(s) or s < 1e-6:
            s = 1.0
        c = huber_k * s
        abs_r = np.abs(resid)
        w = np.ones_like(abs_r)
        mask = abs_r > c
        w[mask] = c / abs_r[mask]
        wx = x_aug * w[:, None]
        wy = y * w
        beta_new, *_ = np.linalg.lstsq(wx, wy, rcond=None)
        if np.linalg.norm(beta_new - beta) < 1e-6:
            beta = beta_new
            break
        beta = beta_new

    return {
        "beta": beta,
        "feature_names": feature_names,
        "med": med,
        "scale": scale,
    }


def apply_model(df: pd.DataFrame, model: dict[str, object], feature_cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    fill_values = np.asarray(model["fill_values"], dtype=float)
    x_frame = df[feature_cols].copy()
    if "clip_low" in model and "clip_high" in model:
        clip_low = pd.Series(model["clip_low"], index=feature_cols)
        clip_high = pd.Series(model["clip_high"], index=feature_cols)
        x_frame = x_frame.clip(lower=clip_low, upper=clip_high, axis=1)
    x_raw = x_frame.to_numpy(dtype=float)
    na_mask = ~np.isfinite(x_raw)
    if na_mask.any():
        x_raw = x_raw.copy()
        x_raw[na_mask] = np.take(fill_values, np.where(na_mask)[1])
    med = np.asarray(model["med"], dtype=float)
    scale = np.asarray(model["scale"], dtype=float)
    beta = np.asarray(model["beta"], dtype=float)
    x = (x_raw - med) / scale
    conf_component = x @ beta[1:]
    pred = beta[0] + conf_component
    return conf_component, pred


def build_pack_samples(
    flight_index: int,
    flight_id: int,
    source_folder: str,
    battery_id: int,
    df_active: pd.DataFrame,
    regime: pd.Series,
    pack_df: pd.DataFrame,
    cfg: Config,
) -> pd.DataFrame:
    pack = str(battery_id)
    left = df_active.sort_values("time(ms)").reset_index(drop=True)
    right = pack_df.sort_values("time(ms)").reset_index(drop=True)
    merged = pd.merge_asof(
        left,
        right,
        on="time(ms)",
        direction="nearest",
        tolerance=1000.0,
    )
    merged["regime"] = regime.to_numpy()

    raw_soh_col = f"bat {pack} soh"
    soc_col = f"bat {pack} soc"
    current_col = f"bat {pack} current"
    temp_avg_col = f"bat {pack} avg cell temp"
    temp_min_col = f"bat {pack} min cell temp"
    temp_max_col = f"bat {pack} max cell temp"
    cap_est_col = f"bat {pack} cap est"
    min_cell_v_col = f"bat {pack} min cell volt"
    max_cell_v_col = f"bat {pack} max cell volt"
    kalman_col = f"bat {pack} kalman soc"
    coulomb_col = f"bat {pack} coulomb soc out"
    rst_col = f"bat {pack} cell flg rst coulomb"
    new_cap_col = f"bat {pack} cell flg new est batt cap"

    out = pd.DataFrame(
        {
            "flight_index": int(flight_index),
            "flight_id": flight_id,
            "source_folder": source_folder,
            "battery_id": str(battery_id),
            "time_ms": merged["time(ms)"].to_numpy(dtype=float),
            "raw_soh": merged[raw_soh_col].to_numpy(dtype=float),
            "soc": merged[soc_col].to_numpy(dtype=float),
            "current_a": merged[current_col].to_numpy(dtype=float),
            "motor_power_kw": merged["motor power"].to_numpy(dtype=float),
            "oat_c": merged["oat"].to_numpy(dtype=float),
            "temp_avg_c": merged[temp_avg_col].to_numpy(dtype=float),
            "temp_spread_c": (
                merged[temp_max_col].to_numpy(dtype=float) - merged[temp_min_col].to_numpy(dtype=float)
            ),
            "cap_est_ah": merged[cap_est_col].to_numpy(dtype=float),
            "volt_spread_v": (
                merged[max_cell_v_col].to_numpy(dtype=float)
                - merged[min_cell_v_col].to_numpy(dtype=float)
            ),
            "kalman_gap_soc": (
                merged[kalman_col].to_numpy(dtype=float) - merged[coulomb_col].to_numpy(dtype=float)
            ),
            "rst_flag": merged[rst_col].to_numpy(dtype=float),
            "new_cap_flag": merged[new_cap_col].to_numpy(dtype=float),
            "regime": merged["regime"].to_numpy(),
        }
    )
    out["abs_current_a"] = np.abs(out["current_a"])
    out["c_rate"] = out["abs_current_a"] / out["cap_est_ah"].replace(0, np.nan)

    dt_s = pd.Series(out["time_ms"]).diff().to_numpy(dtype=float) / 1000.0
    dsoh = pd.Series(out["raw_soh"]).diff().to_numpy(dtype=float)
    jump_rate = np.abs(dsoh) / np.maximum(dt_s / 60.0, 1e-9)

    major_zero = (
        out["raw_soh"].fillna(0).abs() <= 1e-9
    ) & (
        out["soc"].fillna(0).abs() <= 1e-9
    ) & (
        out["current_a"].fillna(0).abs() <= 1e-9
    ) & (
        out["motor_power_kw"].fillna(0).abs() <= 1e-9
    )
    soc_oob = out["soc"].lt(0) | out["soc"].gt(100)
    rst_raw = out["rst_flag"].fillna(0).to_numpy(dtype=float)
    new_cap_raw = out["new_cap_flag"].fillna(0).to_numpy(dtype=float)
    rst_event = (rst_raw > 0) & (np.r_[False, rst_raw[:-1] <= 0])
    new_cap_event = (new_cap_raw > 0) & (np.r_[False, new_cap_raw[:-1] <= 0])
    reset_event = pd.Series(rst_event | new_cap_event)
    impossible_jump = (
        np.isfinite(jump_rate)
        & np.isfinite(dt_s)
        & (dt_s > 0)
        & (dt_s <= cfg.jump_window_max_s)
        & (
            (jump_rate > cfg.max_soh_jump_pct_per_min)
            | (np.abs(dsoh) > cfg.max_soh_jump_abs)
        )
    )
    impossible_jump = pd.Series(impossible_jump).fillna(False)

    feature_cap_est = (~np.isfinite(out["cap_est_ah"])) | (out["cap_est_ah"] < cfg.cap_est_min_ah) | (out["cap_est_ah"] > cfg.cap_est_max_ah)
    feature_kalman_gap = (~np.isfinite(out["kalman_gap_soc"])) | (out["kalman_gap_soc"].abs() > cfg.max_abs_kalman_gap)
    feature_volt_spread = (~np.isfinite(out["volt_spread_v"])) | (out["volt_spread_v"] < 0.0) | (out["volt_spread_v"] > cfg.max_volt_spread_v)
    feature_temp_spread = (~np.isfinite(out["temp_spread_c"])) | (out["temp_spread_c"].abs() > cfg.max_temp_spread_c)
    feature_c_rate = (~np.isfinite(out["c_rate"])) | (out["c_rate"] > cfg.max_c_rate)
    feature_outlier = feature_cap_est | feature_kalman_gap | feature_volt_spread | feature_temp_spread | feature_c_rate

    out["clean_major_zero"] = major_zero.astype(int)
    out["clean_soc_oob"] = soc_oob.astype(int)
    out["clean_reset"] = reset_event.astype(int)
    out["clean_jump"] = impossible_jump.astype(int)
    out["clean_feature_outlier"] = feature_outlier.astype(int)
    out["invalid_any"] = (
        out["clean_major_zero"].astype(bool)
        | out["clean_soc_oob"].astype(bool)
        | out["clean_reset"].astype(bool)
        | out["clean_jump"].astype(bool)
        | out["clean_feature_outlier"].astype(bool)
    )

    out["valid_for_model"] = (~out["invalid_any"]) & np.isfinite(out["raw_soh"].to_numpy(dtype=float)) & np.isfinite(out["soc"].to_numpy(dtype=float))
    return out


def fit_models_and_normalize(samples: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_cols = [
        "temp_avg_c",
        "temp_spread_c",
        "oat_c",
        "motor_power_kw",
        "abs_current_a",
        "c_rate",
        "volt_spread_v",
        "kalman_gap_soc",
        "soc",
        "regime_climb",
        "regime_cruise",
        "regime_pattern",
    ]

    data = samples.copy()
    for r in ["climb", "cruise", "pattern"]:
        data[f"regime_{r}"] = (data["regime"] == r).astype(float)

    model_rows: list[dict[str, object]] = []
    norm_frames: list[pd.DataFrame] = []

    for battery_id in ["1", "2"]:
        bdf = data[data["battery_id"] == battery_id].copy()
        fit_df = bdf[bdf["valid_for_model"]].copy()

        if len(fit_df) < cfg.min_model_rows:
            bdf["confounder_component"] = 0.0
            bdf["soh_observed_norm"] = bdf["raw_soh"]
            bdf["model_used"] = 0
            norm_frames.append(bdf)
            model_rows.append(
                {
                    "battery_id": battery_id,
                    "model_used": 0,
                    "fit_rows": int(len(fit_df)),
                    "intercept": np.nan,
                    "clip_low_json": "{}",
                    "clip_high_json": "{}",
                    "feature_json": "{}",
                }
            )
            continue

        clip_low = fit_df[feature_cols].quantile(cfg.feature_clip_lower_q).fillna(-np.inf)
        clip_high = fit_df[feature_cols].quantile(cfg.feature_clip_upper_q).fillna(np.inf)
        x_fit = fit_df[feature_cols].clip(lower=clip_low, upper=clip_high, axis=1)
        fill_values = x_fit.median(numeric_only=True).fillna(0.0).to_numpy(dtype=float)
        x = x_fit.to_numpy(dtype=float)
        na_mask = ~np.isfinite(x)
        if na_mask.any():
            x = x.copy()
            x[na_mask] = np.take(fill_values, np.where(na_mask)[1])
        y = fit_df["raw_soh"].to_numpy(dtype=float)
        model = robust_huber_fit(
            x_raw=x,
            y=y,
            feature_names=feature_cols,
            huber_k=cfg.huber_k,
            iters=cfg.huber_iters,
        )
        model["fill_values"] = fill_values
        model["clip_low"] = clip_low.to_numpy(dtype=float)
        model["clip_high"] = clip_high.to_numpy(dtype=float)
        conf, pred = apply_model(bdf, model, feature_cols)
        baseline = float(np.nanmedian(conf[bdf["valid_for_model"].to_numpy(dtype=bool)]))
        bdf["confounder_component"] = conf
        bdf["soh_observed_norm"] = bdf["raw_soh"] - conf + baseline
        bdf["model_pred"] = pred
        bdf["model_used"] = 1
        norm_frames.append(bdf)

        beta = np.asarray(model["beta"], dtype=float)
        coeff_map = {"intercept": float(beta[0])}
        for i, name in enumerate(feature_cols, start=1):
            coeff_map[name] = float(beta[i])
        model_rows.append(
                {
                    "battery_id": battery_id,
                    "model_used": 1,
                    "fit_rows": int(len(fit_df)),
                    "intercept": float(beta[0]),
                    "clip_low_json": json.dumps({k: float(v) for k, v in clip_low.to_dict().items()}),
                    "clip_high_json": json.dumps({k: float(v) for k, v in clip_high.to_dict().items()}),
                    "feature_json": json.dumps(coeff_map),
                }
            )

    out_samples = pd.concat(norm_frames, ignore_index=True) if norm_frames else data
    return out_samples, pd.DataFrame(model_rows)


def build_flight_labels(samples_norm: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (flight_id, source_folder, battery_id), g in samples_norm.groupby(
        ["flight_id", "source_folder", "battery_id"], dropna=False
    ):
        total = int(len(g))
        valid = g[g["valid_for_model"]].copy()
        preferred = valid[valid["regime"].isin(["cruise", "pattern"])].copy()
        selected = preferred if len(preferred) >= cfg.min_label_rows_preferred_regime else valid
        if len(selected) < cfg.min_label_rows:
            selected = valid

        if len(selected) > 0:
            label = float(np.nanmedian(selected["soh_observed_norm"]))
            q1 = float(np.nanquantile(selected["soh_observed_norm"], 0.25))
            q3 = float(np.nanquantile(selected["soh_observed_norm"], 0.75))
            iqr = q3 - q1
            raw_median = float(np.nanmedian(selected["raw_soh"]))
        else:
            label = np.nan
            iqr = np.nan
            raw_median = np.nan

        rows.append(
            {
                "flight_index": int(g["flight_index"].iloc[0]) if "flight_index" in g.columns else np.nan,
                "flight_id": int(flight_id),
                "source_folder": source_folder,
                "battery_id": battery_id,
                "soh_observed_norm_flight": label,
                "soh_observed_norm_iqr": iqr,
                "valid_samples_ratio": float(len(valid) / total) if total > 0 else np.nan,
                "valid_samples_count": int(len(valid)),
                "samples_count_total": total,
                "label_source_regime": "cruise_pattern" if selected is preferred and len(preferred) > 0 else "all_valid",
                "raw_soh_median_selected": raw_median,
                "model_used": int(np.nanmax(g["model_used"])) if "model_used" in g.columns else 0,
                "feature_outlier_ratio": float(g["clean_feature_outlier"].mean()) if "clean_feature_outlier" in g.columns else np.nan,
                "invalid_ratio": float(g["invalid_any"].mean()) if "invalid_any" in g.columns else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["flight_index", "battery_id"]).reset_index(drop=True)


def apply_flight_level_cleaning(
    flight_labels: pd.DataFrame,
    cfg: Config,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    metrics_rows: list[dict[str, float | str | int]] = []

    for battery_id, g in flight_labels.groupby("battery_id"):
        g = g.sort_values("flight_index").copy().reset_index(drop=True)
        g["delta_soh_raw"] = g["soh_observed_norm_flight"].diff()
        g["delta_raw_median"] = g["raw_soh_median_selected"].diff()

        delta = g["delta_soh_raw"].to_numpy(dtype=float)
        d_med = np.nanmedian(delta)
        d_mad = 1.4826 * np.nanmedian(np.abs(delta - d_med))
        if not np.isfinite(d_mad) or d_mad < 1e-6:
            d_mad = 0.0
        jump_thr = max(cfg.clean_jump_abs, cfg.clean_jump_mad_mult * d_mad)

        suspect = (
            np.abs(g["delta_soh_raw"].to_numpy(dtype=float)) > jump_thr
        ) & (
            (
                np.abs(g["delta_raw_median"].to_numpy(dtype=float))
                < cfg.clean_jump_raw_confirm_abs
            )
            | (
                g.get("feature_outlier_ratio", pd.Series(np.nan, index=g.index))
                .to_numpy(dtype=float)
                > cfg.clean_feature_outlier_ratio_jump
            )
        )
        suspect = np.where(np.isnan(suspect), False, suspect)

        y = g["soh_observed_norm_flight"].to_numpy(dtype=float).copy()
        y_corr = y.copy()
        idxs = np.flatnonzero(suspect)
        for i in idxs:
            neigh = []
            if i > 0 and np.isfinite(y_corr[i - 1]):
                neigh.append(y_corr[i - 1])
            if i + 1 < len(y_corr) and np.isfinite(y_corr[i + 1]):
                neigh.append(y_corr[i + 1])
            if neigh:
                y_corr[i] = float(np.nanmedian(neigh))

        delta_corr = pd.Series(y_corr).diff().to_numpy(dtype=float)
        raw_confirm = np.abs(g["delta_raw_median"].to_numpy(dtype=float)) >= cfg.clean_jump_raw_confirm_abs
        feature_outlier_high = (
            g.get("feature_outlier_ratio", pd.Series(0.0, index=g.index)).to_numpy(dtype=float)
            > cfg.clean_feature_outlier_ratio_jump
        )
        clip_mask = (
            np.abs(delta_corr) > cfg.clean_delta_cap_abs
        ) & (
            (~raw_confirm) | feature_outlier_high
        )
        transient_pair = np.zeros(len(delta_corr), dtype=bool)
        for i in range(1, len(delta_corr) - 1):
            a = delta_corr[i]
            b = delta_corr[i + 1]
            if (
                np.isfinite(a)
                and np.isfinite(b)
                and (abs(a) >= cfg.clean_transient_pair_abs)
                and (abs(b) >= cfg.clean_transient_pair_abs)
                and (np.sign(a) != np.sign(b))
            ):
                transient_pair[i] = True
                transient_pair[i + 1] = True
        clip_mask = clip_mask | transient_pair
        clip_mask = np.where(np.isnan(clip_mask), False, clip_mask)
        delta_clipped = delta_corr.copy()
        delta_clipped[clip_mask] = np.sign(delta_clipped[clip_mask]) * cfg.clean_delta_cap_abs
        if len(y_corr) > 0:
            y_clean = np.empty_like(y_corr)
            y_clean[0] = y_corr[0]
            for i in range(1, len(y_corr)):
                d = delta_clipped[i]
                if not np.isfinite(d):
                    d = 0.0
                y_clean[i] = y_clean[i - 1] + d
        else:
            y_clean = y_corr.copy()
        y_clean = np.clip(y_clean, 0.0, 100.0)

        g["soh_observed_norm_flight_clean"] = y_clean
        g["clean_jump_flag"] = (suspect | clip_mask).astype(int)
        g["delta_soh_clean"] = pd.Series(y_clean).diff().to_numpy(dtype=float)

        raw_delta = g["delta_soh_raw"].dropna().to_numpy(dtype=float)
        clean_delta = g["delta_soh_clean"].dropna().to_numpy(dtype=float)
        metrics_rows.append(
            {
                "battery_id": str(battery_id),
                "n_flights": int(len(g)),
                "jump_threshold_used": float(jump_thr),
                "raw_delta_std": float(np.std(raw_delta, ddof=1)) if len(raw_delta) > 1 else np.nan,
                "clean_delta_std": float(np.std(clean_delta, ddof=1)) if len(clean_delta) > 1 else np.nan,
                "raw_spikes_abs_gt_5": int(np.sum(np.abs(raw_delta) > 5.0)),
                "clean_spikes_abs_gt_5": int(np.sum(np.abs(clean_delta) > 5.0)),
                "raw_spikes_abs_gt_10": int(np.sum(np.abs(raw_delta) > 10.0)),
                "clean_spikes_abs_gt_10": int(np.sum(np.abs(clean_delta) > 10.0)),
                "suspect_jump_count": int(np.sum(suspect)),
                "delta_clip_count": int(np.sum(clip_mask)),
            }
        )
        frames.append(g)

    out = pd.concat(frames, ignore_index=True) if frames else flight_labels.copy()
    metrics_df = pd.DataFrame(metrics_rows)
    return out, metrics_df


def plot_trends(flight_labels: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(14, 7))
    x_col = "flight_index" if "flight_index" in flight_labels.columns else "flight_id"
    x_label = "Flight Index" if x_col == "flight_index" else "Flight ID"
    for battery_id, color in [("1", "#d62728"), ("2", "#1f77b4")]:
        g = flight_labels[flight_labels["battery_id"] == battery_id].sort_values(x_col)
        if g.empty:
            continue
        ax.plot(g[x_col], g["raw_soh_median_selected"], color=color, alpha=0.35, lw=1.0, label=f"battery {battery_id} raw median")
        ax.plot(g[x_col], g["soh_observed_norm_flight"], color=color, lw=1.0, alpha=0.7, label=f"battery {battery_id} normalized")
        if "soh_observed_norm_flight_clean" in g.columns:
            ax.plot(
                g[x_col],
                g["soh_observed_norm_flight_clean"],
                color=color,
                lw=2.0,
                alpha=0.95,
                linestyle="--",
                label=f"battery {battery_id} cleaned",
            )
    ax.set_title("Observed SOH vs normalized SOH labels by flight")
    ax.set_xlabel(x_label)
    ax.set_ylabel("SOH (%)")
    ax.grid(alpha=0.25)
    ax.legend(loc="best")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_scatter(samples_norm: pd.DataFrame, cfg: Config, out_path: Path) -> None:
    sub = samples_norm[samples_norm["valid_for_model"]].copy()
    if len(sub) > cfg.plot_sample_points:
        sub = sub.sample(n=cfg.plot_sample_points, random_state=42)
    if sub.empty:
        return

    color_map = {"other": "#9e9e9e", "climb": "#ff7f0e", "cruise": "#1f77b4", "pattern": "#2ca02c"}

    fig, ax = plt.subplots(figsize=(9, 8))
    for regime, g in sub.groupby("regime"):
        ax.scatter(
            g["raw_soh"],
            g["soh_observed_norm"],
            s=10,
            alpha=0.3,
            color=color_map.get(str(regime), "#444444"),
            label=str(regime),
        )
    minv = float(np.nanmin([sub["raw_soh"].min(), sub["soh_observed_norm"].min()]))
    maxv = float(np.nanmax([sub["raw_soh"].max(), sub["soh_observed_norm"].max()]))
    ax.plot([minv, maxv], [minv, maxv], color="black", lw=1, linestyle="--", alpha=0.7)
    ax.set_title("Sample-level normalization effect")
    ax.set_xlabel("Raw observed SOH")
    ax.set_ylabel("Normalized observed SOH")
    ax.grid(alpha=0.2)
    ax.legend(loc="best")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def process_plane(cfg: Config) -> dict[str, object]:
    seg_cfg = SegmentationConfig()
    flights = discover_flights(cfg.raw_root, max_flights=cfg.max_flights)
    lookup_df = build_flight_index_lookup(flights)
    flight_index_map = dict(zip(lookup_df["flight_id"], lookup_df["flight_index"]))

    summary: dict[str, object] = {
        "plane_id": cfg.plane_id,
        "raw_root": str(cfg.raw_root),
        "n_folders": len(flights),
        "n_processed": 0,
        "n_active_with_segments": 0,
        "n_errors": 0,
    }
    issues: list[dict[str, object]] = []
    sample_frames: list[pd.DataFrame] = []

    for flight_id, flight_dir in flights:
        flight_index = int(flight_index_map.get(flight_id, np.nan))
        summary["n_processed"] += 1
        main_csv = find_main_csv(flight_dir)
        if main_csv is None:
            issues.append({"flight_index": flight_index, "flight_id": flight_id, "source_folder": flight_dir.name, "issue": "missing_main_csv"})
            continue

        try:
            main_df = load_main_for_norm(main_csv)
        except Exception as exc:
            summary["n_errors"] += 1
            issues.append(
                {
                    "flight_id": flight_id,
                    "flight_index": flight_index,
                    "source_folder": flight_dir.name,
                    "issue": f"main_load_error:{type(exc).__name__}",
                }
            )
            continue

        active_df, phases, seg_issue = segment_flight_dataframe(main_df.copy(), seg_cfg)
        if seg_issue is not None or active_df is None or not phases:
            issues.append(
                {
                    "flight_id": flight_id,
                    "flight_index": flight_index,
                    "source_folder": flight_dir.name,
                    "issue": seg_issue or "segmentation_failed",
                }
            )
            continue
        summary["n_active_with_segments"] += 1

        regime = build_regime_series(active_df, phases)
        for pack in [1, 2]:
            ppath = pack_csv_path(flight_dir, pack)
            if ppath is None:
                issues.append(
                    {
                        "flight_id": flight_id,
                        "flight_index": flight_index,
                        "source_folder": flight_dir.name,
                        "issue": f"missing_pack_{pack}_csv",
                    }
                )
                continue
            try:
                pack_df = load_pack_df(ppath, pack)
            except Exception as exc:
                issues.append(
                    {
                        "flight_id": flight_id,
                        "flight_index": flight_index,
                        "source_folder": flight_dir.name,
                        "issue": f"pack_{pack}_load_error:{type(exc).__name__}",
                    }
                )
                continue

            s = build_pack_samples(
                flight_index=flight_index,
                flight_id=flight_id,
                source_folder=flight_dir.name,
                battery_id=pack,
                df_active=active_df,
                regime=regime,
                pack_df=pack_df,
                cfg=cfg,
            )
            sample_frames.append(s)

    samples = pd.concat(sample_frames, ignore_index=True) if sample_frames else pd.DataFrame()
    if samples.empty:
        raise RuntimeError("No usable samples after preprocessing.")

    samples_norm, model_df = fit_models_and_normalize(samples, cfg)
    flight_labels = build_flight_labels(samples_norm, cfg)
    flight_labels, clean_metrics_df = apply_flight_level_cleaning(flight_labels, cfg)
    issues_df = pd.DataFrame(issues)
    if not issues_df.empty and "flight_index" in issues_df.columns:
        cols = issues_df.columns.tolist()
        cols.remove("flight_index")
        cols.insert(0, "flight_index")
        issues_df = issues_df[cols]

    qa = {
        "plane_id": cfg.plane_id,
        "n_sample_rows": int(len(samples_norm)),
        "n_flights_labeled": int(flight_labels["flight_id"].nunique()),
        "n_flight_pack_rows": int(len(flight_labels)),
        "valid_ratio_mean": float(np.nanmean(samples_norm["valid_for_model"].astype(float))),
        "raw_spikes_abs_gt_10_total": int(
            flight_labels.groupby("battery_id")["delta_soh_raw"].apply(lambda s: (s.abs() > 10).sum()).sum()
        )
        if "delta_soh_raw" in flight_labels.columns
        else np.nan,
        "clean_spikes_abs_gt_10_total": int(
            flight_labels.groupby("battery_id")["delta_soh_clean"].apply(lambda s: (s.abs() > 10).sum()).sum()
        )
        if "delta_soh_clean" in flight_labels.columns
        else np.nan,
    }
    qa_df = pd.DataFrame([qa])

    out_root = cfg.out_dir / f"plane_{cfg.plane_id}"
    out_root.mkdir(parents=True, exist_ok=True)
    plot_dir = out_root / "plots"

    samples_cols = [
        "flight_index",
        "flight_id",
        "source_folder",
        "battery_id",
        "time_ms",
        "regime",
        "raw_soh",
        "soh_observed_norm",
        "confounder_component",
        "valid_for_model",
        "clean_major_zero",
        "clean_soc_oob",
        "clean_reset",
        "clean_jump",
        "clean_feature_outlier",
    ]
    samples_norm[samples_cols].to_csv(out_root / "soh_observed_norm_samples.csv", index=False)
    flight_labels.to_csv(out_root / "soh_observed_norm_flight_labels.csv", index=False)
    model_df.to_csv(out_root / "normalization_model_coefficients.csv", index=False)
    clean_metrics_df.to_csv(out_root / "cleaning_metrics.csv", index=False)
    issues_df.to_csv(out_root / "pipeline_issues.csv", index=False)
    lookup_df.to_csv(out_root / "flight_index_lookup.csv", index=False)
    qa_df.to_csv(out_root / "qa_summary.csv", index=False)

    plot_trends(flight_labels, plot_dir / "normalized_label_trend.png")
    plot_scatter(samples_norm, cfg, plot_dir / "sample_normalization_scatter.png")

    summary["output_dir"] = str(out_root)
    summary["flight_labels_csv"] = str(out_root / "soh_observed_norm_flight_labels.csv")
    summary["sample_labels_csv"] = str(out_root / "soh_observed_norm_samples.csv")
    summary["issues_csv"] = str(out_root / "pipeline_issues.csv")
    summary["qa_csv"] = str(out_root / "qa_summary.csv")
    summary["cleaning_metrics_csv"] = str(out_root / "cleaning_metrics.csv")
    summary["flight_index_lookup_csv"] = str(out_root / "flight_index_lookup.csv")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Approach B normalized observed SOH pipeline. "
            "Builds cleaned sample-level observed SOH, removes confounders with robust regression, "
            "and aggregates to flight-level soh_observed_norm labels."
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
        default=Path("ml_workspace/SOH_normalized/output/observed_norm"),
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = Config(
        raw_root=args.raw_root,
        out_dir=args.out_dir,
        plane_id=args.plane_id,
        max_flights=args.max_flights,
    )
    summary = process_plane(cfg)
    print(pd.Series(summary).to_string())


if __name__ == "__main__":
    main()
