from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


@dataclass
class Config:
    labels_csv: Path
    feature_csv: Path
    out_dir: Path
    huber_k: float = 1.5
    huber_iters: int = 30


def huber_fit(x: np.ndarray, y: np.ndarray, iters: int, huber_k: float) -> np.ndarray:
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    for _ in range(iters):
        resid = y - x @ beta
        scale = 1.4826 * np.median(np.abs(resid - np.median(resid)))
        if not np.isfinite(scale) or scale < 1e-8:
            scale = 1.0
        c = huber_k * scale
        w = np.ones_like(resid)
        m = np.abs(resid) > c
        w[m] = c / np.abs(resid[m])
        xw = x * w[:, None]
        yw = y * w
        beta_new, *_ = np.linalg.lstsq(xw, yw, rcond=None)
        if np.linalg.norm(beta_new - beta) < 1e-9:
            beta = beta_new
            break
        beta = beta_new
    return beta


def linear_fit_r2(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    if len(x) < 3:
        return np.nan, np.nan
    coef = np.polyfit(x, y, 1)
    pred = coef[0] * x + coef[1]
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else np.nan
    return float(coef[0]), float(r2)


def build_metrics(df: pd.DataFrame, value_col: str, delta_col: str) -> dict[str, float]:
    d = df[delta_col].dropna().to_numpy(dtype=float)
    y = df[value_col].to_numpy(dtype=float)
    x = df["flight_index"].to_numpy(dtype=float)
    slope, r2 = linear_fit_r2(x, y)
    return {
        "delta_std": float(np.std(d, ddof=1)) if len(d) > 1 else np.nan,
        "spikes_abs_gt_5": int(np.sum(np.abs(d) > 5.0)),
        "spikes_abs_gt_10": int(np.sum(np.abs(d) > 10.0)),
        "positive_jumps_gt_3": int(np.sum(d > 3.0)),
        "negative_jumps_lt_-3": int(np.sum(d < -3.0)),
        "slope_per_flight": slope,
        "linear_r2": r2,
    }


def run_scenario_for_battery(
    g: pd.DataFrame,
    feature_cols: list[str],
    huber_k: float,
    huber_iters: int,
) -> tuple[pd.DataFrame, dict[str, float], dict[str, float]]:
    work = g.sort_values("flight_index").copy()
    work["delta_raw"] = work["soh_observed_norm_flight"].diff()

    for col in feature_cols:
        if col not in work.columns:
            raise ValueError(f"Missing feature column: {col}")

    use = work.dropna(subset=["delta_raw"] + feature_cols).copy()
    if len(use) < 15:
        work["delta_corr"] = work["delta_raw"]
        y0 = float(work["soh_observed_norm_flight"].iloc[0])
        work["soh_corr"] = y0 + work["delta_corr"].fillna(0.0).cumsum()
        work["pred_component"] = 0.0
        coeff = {"intercept": 0.0}
        return work, build_metrics(work, "soh_observed_norm_flight", "delta_raw"), coeff

    x_raw = use[feature_cols].to_numpy(dtype=float)
    mu = np.nanmean(x_raw, axis=0)
    sd = np.nanstd(x_raw, axis=0)
    sd[~np.isfinite(sd) | (sd < 1e-8)] = 1.0
    x = (x_raw - mu) / sd
    x = np.column_stack([np.ones(len(use)), x])
    y = use["delta_raw"].to_numpy(dtype=float)

    beta = huber_fit(x, y, iters=huber_iters, huber_k=huber_k)
    pred = x @ beta
    pred_centered = pred - np.mean(pred)
    use["pred_component"] = pred_centered
    use["delta_corr"] = use["delta_raw"] - use["pred_component"]

    work["delta_corr"] = np.nan
    work["pred_component"] = np.nan
    work.loc[use.index, "delta_corr"] = use["delta_corr"]
    work.loc[use.index, "pred_component"] = use["pred_component"]
    work["delta_corr"] = work["delta_corr"].fillna(work["delta_raw"])
    work["pred_component"] = work["pred_component"].fillna(0.0)

    y0 = float(work["soh_observed_norm_flight"].iloc[0])
    work["soh_corr"] = y0 + work["delta_corr"].fillna(0.0).cumsum()

    coeff = {"intercept": float(beta[0])}
    for i, c in enumerate(feature_cols, start=1):
        coeff[c] = float(beta[i])

    return work, build_metrics(work, "soh_observed_norm_flight", "delta_raw"), coeff


def plot_series(df: pd.DataFrame, out_path: Path) -> None:
    scenarios = list(df["scenario"].unique())
    bats = ["1", "2"]
    fig, axes = plt.subplots(len(bats), len(scenarios), figsize=(7 * len(scenarios), 5 * len(bats)), sharex=True)
    if len(bats) == 1 and len(scenarios) == 1:
        axes = np.array([[axes]])
    elif len(bats) == 1:
        axes = np.array([axes])
    elif len(scenarios) == 1:
        axes = np.array([[ax] for ax in axes])

    for r, b in enumerate(bats):
        for c, s in enumerate(scenarios):
            ax = axes[r, c]
            g = df[(df["battery_id"] == b) & (df["scenario"] == s)].sort_values("flight_index")
            if g.empty:
                ax.axis("off")
                continue
            ax.plot(g["flight_index"], g["soh_observed_norm_flight"], color="#444444", alpha=0.55, lw=1.1, label="raw normalized SOH")
            ax.plot(g["flight_index"], g["soh_corr"], color="#1f77b4", lw=1.2, label="corrected SOH")
            ax.axvline(300, color="#888888", linestyle="--", lw=1.0)
            ax.set_title(f"Battery {b} | {s}")
            ax.set_xlabel("Flight index")
            ax.set_ylabel("SOH (%)")
            ax.grid(alpha=0.25)
            ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_delta(df: pd.DataFrame, out_path: Path) -> None:
    scenarios = list(df["scenario"].unique())
    bats = ["1", "2"]
    fig, axes = plt.subplots(len(bats), len(scenarios), figsize=(7 * len(scenarios), 5 * len(bats)), sharex=True)
    if len(bats) == 1 and len(scenarios) == 1:
        axes = np.array([[axes]])
    elif len(bats) == 1:
        axes = np.array([axes])
    elif len(scenarios) == 1:
        axes = np.array([[ax] for ax in axes])

    for r, b in enumerate(bats):
        for c, s in enumerate(scenarios):
            ax = axes[r, c]
            g = df[(df["battery_id"] == b) & (df["scenario"] == s)].sort_values("flight_index")
            if g.empty:
                ax.axis("off")
                continue
            ax.plot(g["flight_index"], g["delta_raw"], color="#444444", alpha=0.45, lw=1.0, label="raw delta")
            ax.plot(g["flight_index"], g["delta_corr"], color="#d62728", lw=1.0, label="corrected delta")
            ax.axhline(0, color="#999999", lw=0.8)
            ax.axvline(300, color="#888888", linestyle="--", lw=1.0)
            ax.set_title(f"Battery {b} delta | {s}")
            ax.set_xlabel("Flight index")
            ax.set_ylabel("Delta SOH")
            ax.grid(alpha=0.25)
            ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Test whether correlated features (especially temperature/OAT) reduce spikes "
            "in normalized observed SOH by correcting flight-to-flight deltas."
        )
    )
    parser.add_argument(
        "--labels-csv",
        type=Path,
        default=Path("ml_workspace/SOH_normalized/output/observed_norm/plane_166/soh_observed_norm_flight_labels.csv"),
    )
    parser.add_argument(
        "--feature-csv",
        type=Path,
        default=Path("ml_workspace/SOH_normalized/output/observed_norm/plane_166/analysis/flight_feature_summary.csv"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("ml_workspace/SOH_normalized/output/observed_norm/plane_166/spike_normalization"),
    )
    args = parser.parse_args()

    cfg = Config(labels_csv=args.labels_csv, feature_csv=args.feature_csv, out_dir=args.out_dir)
    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    labels = pd.read_csv(cfg.labels_csv)
    feats = pd.read_csv(cfg.feature_csv)
    labels["battery_id"] = labels["battery_id"].astype(str)
    feats["battery_id"] = feats["battery_id"].astype(str)

    merged = labels.merge(
        feats,
        on=["flight_index", "flight_id", "source_folder", "battery_id"],
        how="inner",
    ).sort_values(["battery_id", "flight_index"]).reset_index(drop=True)

    for col in [
        "temp_avg_mean",
        "oat_mean",
        "kalman_gap_abs_mean",
        "volt_spread_mean",
        "cap_est_mean",
    ]:
        merged[f"d_{col}"] = merged.groupby("battery_id")[col].diff()

    scenarios = {
        "seasonal_only": ["d_temp_avg_mean", "d_oat_mean"],
        "top_correlated": [
            "d_temp_avg_mean",
            "d_oat_mean",
            "d_kalman_gap_abs_mean",
            "d_volt_spread_mean",
            "d_cap_est_mean",
        ],
    }

    all_rows: list[pd.DataFrame] = []
    metrics_rows: list[dict[str, float | str | int]] = []
    coeff_rows: list[dict[str, str | float]] = []

    for scenario, feature_cols in scenarios.items():
        for battery_id, g in merged.groupby("battery_id"):
            out, raw_metrics, coeff = run_scenario_for_battery(
                g=g,
                feature_cols=feature_cols,
                huber_k=cfg.huber_k,
                huber_iters=cfg.huber_iters,
            )
            out["scenario"] = scenario
            all_rows.append(out)

            corr_metrics = build_metrics(out, "soh_corr", "delta_corr")
            row = {
                "scenario": scenario,
                "battery_id": battery_id,
                "n_flights": int(len(out)),
                "raw_delta_std": raw_metrics["delta_std"],
                "corr_delta_std": corr_metrics["delta_std"],
                "raw_spikes_abs_gt_5": raw_metrics["spikes_abs_gt_5"],
                "corr_spikes_abs_gt_5": corr_metrics["spikes_abs_gt_5"],
                "raw_spikes_abs_gt_10": raw_metrics["spikes_abs_gt_10"],
                "corr_spikes_abs_gt_10": corr_metrics["spikes_abs_gt_10"],
                "raw_linear_r2": raw_metrics["linear_r2"],
                "corr_linear_r2": corr_metrics["linear_r2"],
                "raw_slope_per_flight": raw_metrics["slope_per_flight"],
                "corr_slope_per_flight": corr_metrics["slope_per_flight"],
                "raw_positive_jumps_gt_3": raw_metrics["positive_jumps_gt_3"],
                "corr_positive_jumps_gt_3": corr_metrics["positive_jumps_gt_3"],
            }
            metrics_rows.append(row)

            coeff_rows.append(
                {
                    "scenario": scenario,
                    "battery_id": battery_id,
                    "coeff_json": json.dumps(coeff),
                }
            )

    result = pd.concat(all_rows, ignore_index=True)
    metrics_df = pd.DataFrame(metrics_rows)
    coeff_df = pd.DataFrame(coeff_rows)

    keep_cols = [
        "scenario",
        "battery_id",
        "flight_index",
        "flight_id",
        "source_folder",
        "soh_observed_norm_flight",
        "soh_corr",
        "delta_raw",
        "delta_corr",
        "pred_component",
        "d_temp_avg_mean",
        "d_oat_mean",
        "d_kalman_gap_abs_mean",
        "d_volt_spread_mean",
        "d_cap_est_mean",
    ]
    result[keep_cols].to_csv(cfg.out_dir / "soh_spike_correction_series.csv", index=False)
    metrics_df.to_csv(cfg.out_dir / "soh_spike_correction_metrics.csv", index=False)
    coeff_df.to_csv(cfg.out_dir / "soh_spike_correction_coefficients.csv", index=False)

    plot_series(result, cfg.out_dir / "soh_raw_vs_corrected.png")
    plot_delta(result, cfg.out_dir / "delta_raw_vs_corrected.png")

    print(f"wrote: {cfg.out_dir}")
    print(metrics_df.to_string(index=False))


if __name__ == "__main__":
    main()
