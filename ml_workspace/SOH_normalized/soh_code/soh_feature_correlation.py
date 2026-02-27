from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from flight_segmentation import SegmentationConfig, find_main_csv, segment_flight_dataframe


@dataclass
class Config:
    raw_root: Path
    labels_csv: Path
    out_dir: Path
    min_points_corr: int = 25
    top_n_plot: int = 8


def normalize_col(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def load_main_for_features(path: Path) -> pd.DataFrame:
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
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time(ms)"]).sort_values("time(ms)").reset_index(drop=True)
    df = df.loc[df["time(ms)"].diff().fillna(1.0) > 0].copy()
    if df.empty:
        raise ValueError("empty_main")
    t0 = float(df["time(ms)"].iloc[0])
    df["time_s"] = (df["time(ms)"] - t0) / 1000.0
    return df


def load_pack_for_features(path: Path, battery_id: int) -> pd.DataFrame:
    p = str(battery_id)
    needed = {
        "time(ms)",
        f"bat {p} avg cell temp",
        f"bat {p} min cell temp",
        f"bat {p} max cell temp",
        f"bat {p} min cell volt",
        f"bat {p} max cell volt",
        f"bat {p} cap est",
        f"bat {p} kalman soc",
        f"bat {p} coulomb soc out",
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
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time(ms)"]).sort_values("time(ms)").reset_index(drop=True)
    df = df.loc[df["time(ms)"].diff().fillna(1.0) > 0].copy()
    return df


def pack_csv_path(flight_dir: Path, battery_id: int) -> Path | None:
    suffix = f"_{battery_id}.csv"
    for p in sorted(flight_dir.glob("*.csv")):
        if p.name.lower().endswith(suffix):
            return p
    return None


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
        regime.iloc[s : e + 1] = phase_to_regime(str(p["phase_key"]))
    return regime


def ratio_of(regime: pd.Series, name: str) -> float:
    if len(regime) == 0:
        return np.nan
    return float((regime == name).mean())


def build_pack_flight_features(
    flight_index: int,
    flight_id: int,
    source_folder: str,
    battery_id: int,
    active_main: pd.DataFrame,
    regime: pd.Series,
    pack_df: pd.DataFrame,
) -> dict[str, float | int | str]:
    p = str(battery_id)
    merged = pd.merge_asof(
        active_main.sort_values("time(ms)").reset_index(drop=True),
        pack_df.sort_values("time(ms)").reset_index(drop=True),
        on="time(ms)",
        direction="nearest",
        tolerance=1000.0,
    )
    merged["regime"] = regime.to_numpy()

    soc = merged[f"bat {p} soc"].to_numpy(dtype=float)
    current = merged[f"bat {p} current"].to_numpy(dtype=float)
    cap_est = merged[f"bat {p} cap est"].to_numpy(dtype=float)
    kalman_gap = (
        merged[f"bat {p} kalman soc"].to_numpy(dtype=float)
        - merged[f"bat {p} coulomb soc out"].to_numpy(dtype=float)
    )
    volt_spread = (
        merged[f"bat {p} max cell volt"].to_numpy(dtype=float)
        - merged[f"bat {p} min cell volt"].to_numpy(dtype=float)
    )
    temp_spread = (
        merged[f"bat {p} max cell temp"].to_numpy(dtype=float)
        - merged[f"bat {p} min cell temp"].to_numpy(dtype=float)
    )
    c_rate = np.abs(current) / np.where(np.abs(cap_est) > 1e-6, cap_est, np.nan)

    valid_soc = soc[np.isfinite(soc)]
    soc_drop = float(valid_soc[0] - valid_soc[-1]) if valid_soc.size >= 2 else np.nan

    return {
        "flight_index": int(flight_index),
        "flight_id": int(flight_id),
        "source_folder": source_folder,
        "battery_id": str(battery_id),
        "n_active_rows": int(len(active_main)),
        "duration_min": float(active_main["time_s"].iloc[-1] - active_main["time_s"].iloc[0]) / 60.0,
        "motor_power_mean": float(np.nanmean(active_main["motor power"])),
        "motor_power_p95": float(np.nanpercentile(active_main["motor power"], 95)),
        "ias_mean": float(np.nanmean(active_main["ias"])),
        "oat_mean": float(np.nanmean(active_main["oat"])),
        "soc_drop": soc_drop,
        "abs_current_mean": float(np.nanmean(np.abs(current))),
        "abs_current_p95": float(np.nanpercentile(np.abs(current), 95)),
        "temp_avg_mean": float(np.nanmean(merged[f"bat {p} avg cell temp"])),
        "temp_spread_mean": float(np.nanmean(temp_spread)),
        "volt_spread_mean": float(np.nanmean(volt_spread)),
        "cap_est_mean": float(np.nanmean(cap_est)),
        "c_rate_mean": float(np.nanmean(c_rate)),
        "kalman_gap_abs_mean": float(np.nanmean(np.abs(kalman_gap))),
        "regime_climb_ratio": ratio_of(regime, "climb"),
        "regime_cruise_ratio": ratio_of(regime, "cruise"),
        "regime_pattern_ratio": ratio_of(regime, "pattern"),
    }


def calc_corr(x: pd.Series, y: pd.Series, min_points: int) -> tuple[int, float, float]:
    m = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
    n = int(m.sum())
    if n < min_points:
        return n, np.nan, np.nan
    x2 = x[m]
    y2 = y[m]
    pearson = float(x2.corr(y2, method="pearson"))
    spearman = float(x2.corr(y2, method="spearman"))
    return n, pearson, spearman


def zscore(s: pd.Series) -> pd.Series:
    mu = s.mean(skipna=True)
    sd = s.std(skipna=True)
    if not np.isfinite(sd) or sd < 1e-9:
        return s * 0.0
    return (s - mu) / sd


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Correlate non-time flight features with normalized SOH changes "
            "(Approach B soh_observed_norm)."
        )
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/raw_csv/by_plane/166"),
    )
    parser.add_argument(
        "--labels-csv",
        type=Path,
        default=Path("ml_workspace/SOH_normalized/output/observed_norm/plane_166/soh_observed_norm_flight_labels.csv"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("ml_workspace/SOH_normalized/output/observed_norm/plane_166/analysis"),
    )
    args = parser.parse_args()

    cfg = Config(raw_root=args.raw_root, labels_csv=args.labels_csv, out_dir=args.out_dir)
    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    labels = pd.read_csv(cfg.labels_csv)
    labels["battery_id"] = labels["battery_id"].astype(str)
    flight_keys = (
        labels[["flight_index", "flight_id", "source_folder"]]
        .drop_duplicates()
        .sort_values("flight_index")
        .reset_index(drop=True)
    )

    seg_cfg = SegmentationConfig()
    feature_rows: list[dict[str, float | int | str]] = []
    issues: list[dict[str, str | int]] = []

    for _, fk in flight_keys.iterrows():
        flight_index = int(fk["flight_index"])
        flight_id = int(fk["flight_id"])
        source_folder = str(fk["source_folder"])
        flight_dir = cfg.raw_root / source_folder
        if not flight_dir.exists():
            issues.append(
                {
                    "flight_index": flight_index,
                    "flight_id": flight_id,
                    "source_folder": source_folder,
                    "issue": "missing_source_folder",
                }
            )
            continue

        main_csv = find_main_csv(flight_dir)
        if main_csv is None:
            issues.append(
                {
                    "flight_index": flight_index,
                    "flight_id": flight_id,
                    "source_folder": source_folder,
                    "issue": "missing_main_csv",
                }
            )
            continue
        try:
            main_df = load_main_for_features(main_csv)
            active_df, phases, seg_issue = segment_flight_dataframe(main_df.copy(), seg_cfg)
            if seg_issue is not None or active_df is None or not phases:
                issues.append(
                    {
                        "flight_index": flight_index,
                        "flight_id": flight_id,
                        "source_folder": source_folder,
                        "issue": seg_issue or "segmentation_failed",
                    }
                )
                continue
            regime = build_regime_series(active_df, phases)
        except Exception as exc:
            issues.append(
                {
                    "flight_index": flight_index,
                    "flight_id": flight_id,
                    "source_folder": source_folder,
                    "issue": f"main_or_seg_error:{type(exc).__name__}",
                }
            )
            continue

        for battery_id in [1, 2]:
            pack_csv = pack_csv_path(flight_dir, battery_id)
            if pack_csv is None:
                issues.append(
                    {
                        "flight_index": flight_index,
                        "flight_id": flight_id,
                        "source_folder": source_folder,
                        "issue": f"missing_pack_{battery_id}_csv",
                    }
                )
                continue
            try:
                pack_df = load_pack_for_features(pack_csv, battery_id)
                row = build_pack_flight_features(
                    flight_index=flight_index,
                    flight_id=flight_id,
                    source_folder=source_folder,
                    battery_id=battery_id,
                    active_main=active_df,
                    regime=regime,
                    pack_df=pack_df,
                )
                feature_rows.append(row)
            except Exception as exc:
                issues.append(
                    {
                        "flight_index": flight_index,
                        "flight_id": flight_id,
                        "source_folder": source_folder,
                        "issue": f"pack_{battery_id}_error:{type(exc).__name__}",
                    }
                )

    features = pd.DataFrame(feature_rows)
    if not features.empty and "battery_id" in features.columns:
        features["battery_id"] = features["battery_id"].astype(str)
    issues_df = pd.DataFrame(issues)
    features.to_csv(cfg.out_dir / "flight_feature_summary.csv", index=False)
    issues_df.to_csv(cfg.out_dir / "feature_build_issues.csv", index=False)

    merged = labels.merge(
        features,
        on=["flight_index", "flight_id", "source_folder", "battery_id"],
        how="inner",
    ).sort_values(["battery_id", "flight_index"]).reset_index(drop=True)
    merged["delta_soh_observed_norm"] = merged.groupby("battery_id")["soh_observed_norm_flight"].diff()

    feature_cols = [
        "duration_min",
        "motor_power_mean",
        "motor_power_p95",
        "ias_mean",
        "oat_mean",
        "soc_drop",
        "abs_current_mean",
        "abs_current_p95",
        "temp_avg_mean",
        "temp_spread_mean",
        "volt_spread_mean",
        "cap_est_mean",
        "c_rate_mean",
        "kalman_gap_abs_mean",
        "regime_climb_ratio",
        "regime_cruise_ratio",
        "regime_pattern_ratio",
    ]
    for c in feature_cols:
        merged[f"d_{c}"] = merged.groupby("battery_id")[c].diff()

    corr_rows: list[dict[str, float | int | str]] = []
    for feature in feature_cols:
        for kind, col in [("level", feature), ("delta_feature", f"d_{feature}")]:
            n, pearson, spearman = calc_corr(
                merged[col],
                merged["delta_soh_observed_norm"],
                cfg.min_points_corr,
            )
            corr_rows.append(
                {
                    "feature": feature,
                    "kind": kind,
                    "analysis_col": col,
                    "n": n,
                    "pearson_r": pearson,
                    "spearman_r": spearman,
                    "abs_spearman_r": abs(spearman) if np.isfinite(spearman) else np.nan,
                }
            )

    corr_df = pd.DataFrame(corr_rows).sort_values("abs_spearman_r", ascending=False)
    corr_df.to_csv(cfg.out_dir / "feature_correlation_with_delta_soh.csv", index=False)

    top = corr_df.dropna(subset=["abs_spearman_r"]).head(cfg.top_n_plot).copy()
    top = top[::-1]

    fig, ax = plt.subplots(figsize=(11, 7))
    labels_bar = [f"{r.feature} ({'dX' if r.kind == 'delta_feature' else 'X'})" for r in top.itertuples()]
    vals = top["spearman_r"].to_numpy(dtype=float)
    colors = ["#1f77b4" if v >= 0 else "#d62728" for v in vals]
    ax.barh(labels_bar, vals, color=colors, alpha=0.85)
    ax.set_xlabel("Spearman r with delta_soh_observed_norm")
    ax.set_title("Top non-time features correlated with normalized SOH change")
    ax.grid(alpha=0.25, axis="x")
    fig.tight_layout()
    fig.savefig(cfg.out_dir / "top_correlations_bar.png", dpi=150)
    plt.close(fig)

    top4 = corr_df.dropna(subset=["abs_spearman_r"]).head(4).copy()
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    axes = axes.flatten()
    for i, row in enumerate(top4.itertuples()):
        ax = axes[i]
        x = merged[row.analysis_col]
        y = merged["delta_soh_observed_norm"]
        m = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
        ax.scatter(x[m], y[m], s=10, alpha=0.28, color="#1f77b4")
        if int(m.sum()) > 10:
            xfit = x[m].to_numpy(dtype=float)
            yfit = y[m].to_numpy(dtype=float)
            coef = np.polyfit(xfit, yfit, 1)
            xx = np.linspace(np.nanpercentile(xfit, 2), np.nanpercentile(xfit, 98), 60)
            yy = coef[0] * xx + coef[1]
            ax.plot(xx, yy, color="#d62728", linewidth=1.5)
        ax.set_title(f"{row.feature} ({'dX' if row.kind=='delta_feature' else 'X'})")
        ax.set_xlabel(row.analysis_col)
        ax.set_ylabel("delta_soh_observed_norm")
        ax.grid(alpha=0.2)
    for j in range(len(top4), 4):
        axes[j].axis("off")
    fig.tight_layout()
    fig.savefig(cfg.out_dir / "top_correlations_scatter.png", dpi=150)
    plt.close(fig)

    trend_features = corr_df.dropna(subset=["abs_spearman_r"]).head(2)["analysis_col"].tolist()
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    for ax, battery_id in zip(axes, ["1", "2"]):
        g = merged[merged["battery_id"] == battery_id].sort_values("flight_index").copy()
        if g.empty:
            continue
        ax.plot(
            g["flight_index"],
            zscore(g["delta_soh_observed_norm"]),
            color="#111111",
            linewidth=1.4,
            label="z(delta_soh)",
        )
        for col, color in zip(trend_features, ["#1f77b4", "#ff7f0e"]):
            ax.plot(
                g["flight_index"],
                zscore(g[col]),
                linewidth=1.0,
                alpha=0.85,
                color=color,
                label=f"z({col})",
            )
        ax.axvline(300, color="#666666", linestyle="--", linewidth=1.0)
        ax.set_title(f"Battery {battery_id} trend (marker at flight index 300)")
        ax.set_ylabel("z-score")
        ax.grid(alpha=0.25)
        ax.legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("Flight index")
    fig.tight_layout()
    fig.savefig(cfg.out_dir / "delta_soh_feature_trends.png", dpi=150)
    plt.close(fig)

    print(f"wrote: {cfg.out_dir}")
    print(f"rows_used: {len(merged)}")
    print("top_correlations:")
    print(corr_df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
