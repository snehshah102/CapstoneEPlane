from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


@dataclass
class Config:
    labels_csv: Path
    feature_csv: Path
    raw_root: Path
    out_dir: Path
    raw_jump_abs_threshold: float = 10.0
    top_plot_jumps: int = 4
    pre_window: int = 5
    post_window: int = 10


def normalize_col(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def load_warn_features(raw_root: Path, keys: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    for _, r in keys.iterrows():
        source_folder = str(r["source_folder"])
        flight_id = int(r["flight_id"])
        flight_dir = raw_root / source_folder
        warn_file = next((p for p in flight_dir.glob("*_warns.csv")), None)
        base = {
            "flight_id": flight_id,
            "source_folder": source_folder,
            "warn_duration_min": np.nan,
            "stall_warn_minutes": np.nan,
            "soc30_warn_minutes": np.nan,
            "drive_temp_warn_minutes": np.nan,
        }
        if warn_file is None:
            rows.append(base)
            continue
        try:
            df = pd.read_csv(warn_file, skipinitialspace=True, low_memory=False)
        except Exception:
            rows.append(base)
            continue
        if df.empty:
            base.update(
                {
                    "warn_duration_min": 0.0,
                    "stall_warn_minutes": 0.0,
                    "soc30_warn_minutes": 0.0,
                    "drive_temp_warn_minutes": 0.0,
                }
            )
            rows.append(base)
            continue

        df = df.rename(columns={c: normalize_col(c) for c in df.columns})
        if "time(min)" not in df.columns:
            rows.append(base)
            continue
        df["time(min)"] = pd.to_numeric(df["time(min)"], errors="coerce")
        df = df.dropna(subset=["time(min)"]).sort_values("time(min)").reset_index(drop=True)
        if df.empty:
            base.update(
                {
                    "warn_duration_min": 0.0,
                    "stall_warn_minutes": 0.0,
                    "soc30_warn_minutes": 0.0,
                    "drive_temp_warn_minutes": 0.0,
                }
            )
            rows.append(base)
            continue

        dt = df["time(min)"].diff().fillna(0.0).clip(lower=0.0, upper=2.0)
        stall = pd.to_numeric(df.get("stall warning", pd.Series(0, index=df.index)), errors="coerce").fillna(0.0)
        soc30 = pd.to_numeric(df.get("soc<30%", pd.Series(0, index=df.index)), errors="coerce").fillna(0.0)
        drive_temp = pd.to_numeric(df.get("drive high temp", pd.Series(0, index=df.index)), errors="coerce").fillna(0.0)

        base.update(
            {
                "warn_duration_min": float(df["time(min)"].iloc[-1] - df["time(min)"].iloc[0]),
                "stall_warn_minutes": float((dt * (stall > 0)).sum()),
                "soc30_warn_minutes": float((dt * (soc30 > 0)).sum()),
                "drive_temp_warn_minutes": float((dt * (drive_temp > 0)).sum()),
            }
        )
        rows.append(base)
    return pd.DataFrame(rows)


def zscore(series: pd.Series) -> pd.Series:
    std = series.std(skipna=True)
    if not np.isfinite(std) or std < 1e-9:
        return pd.Series(np.zeros(len(series)), index=series.index)
    return (series - series.mean(skipna=True)) / std


def build_reason(row: pd.Series) -> str:
    reasons: list[str] = []
    if max(abs(float(row.get("d_temp_avg_mean", 0.0) or 0.0)), abs(float(row.get("d_oat_mean", 0.0) or 0.0))) >= 4.0:
        reasons.append("thermal_shift")
    if max(
        abs(float(row.get("d_cap_est_mean", 0.0) or 0.0)),
        abs(float(row.get("d_kalman_gap_abs_mean", 0.0) or 0.0)),
        abs(float(row.get("d_volt_spread_mean", 0.0) or 0.0)),
    ) >= 150.0 or abs(float(row.get("d_kalman_gap_abs_mean", 0.0) or 0.0)) >= 0.7 or abs(float(row.get("d_volt_spread_mean", 0.0) or 0.0)) >= 2.5:
        reasons.append("estimator_shift")
    if float(row.get("soc30_warn_minutes", 0.0) or 0.0) >= 2.0:
        reasons.append("low_soc_warning")
    if float(row.get("drive_temp_warn_minutes", 0.0) or 0.0) >= 2.0:
        reasons.append("drive_temp_warning")
    if abs(float(row.get("d_soc_drop", 0.0) or 0.0)) >= 8.0 or abs(float(row.get("d_duration_min", 0.0) or 0.0)) >= 8.0:
        reasons.append("mission_profile_shift")
    if float(row.get("feature_outlier_ratio", 0.0) or 0.0) >= 0.05:
        reasons.append("feature_outliers")
    if float(row.get("invalid_ratio", 0.0) or 0.0) >= 0.05:
        reasons.append("invalid_samples")
    if not reasons:
        reasons.append("weak_driver_signal")
    return "|".join(reasons)


def correlation_rows(df: pd.DataFrame, target_col: str, feature_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    for battery_id, g in df.groupby("battery_id"):
        for feature in feature_cols:
            x = g[target_col]
            y = g[feature]
            mask = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
            n = int(mask.sum())
            if n < 12:
                pearson = np.nan
                spearman = np.nan
            else:
                pearson = float(x[mask].corr(y[mask], method="pearson"))
                spearman = float(x[mask].corr(y[mask], method="spearman"))
            rows.append(
                {
                    "battery_id": str(battery_id),
                    "target": target_col,
                    "feature": feature,
                    "n": n,
                    "pearson": pearson,
                    "spearman": spearman,
                    "abs_spearman": abs(spearman) if np.isfinite(spearman) else np.nan,
                }
            )
    out = pd.DataFrame(rows)
    return out.sort_values(["battery_id", "abs_spearman"], ascending=[True, False]).reset_index(drop=True)


def add_deltas(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for battery_id, idx in out.groupby("battery_id").groups.items():
        g = out.loc[idx].sort_values("flight_id")
        out.loc[g.index, "chron_index"] = np.arange(1, len(g) + 1)
        out.loc[g.index, "d_raw_soh"] = g["raw_soh_median_selected"].diff().to_numpy()
        out.loc[g.index, "d_norm_soh"] = g["soh_observed_norm_flight"].diff().to_numpy()
        out.loc[g.index, "d_clean_soh"] = g["soh_observed_norm_flight_clean"].diff().to_numpy()
        out.loc[g.index, "gap_flight_id"] = g["flight_id"].diff().to_numpy()
        for col in cols:
            out.loc[g.index, f"d_{col}"] = g[col].diff().to_numpy()
    return out


def build_jump_table(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    feature_cols = [
        "temp_avg_mean",
        "oat_mean",
        "cap_est_mean",
        "kalman_gap_abs_mean",
        "volt_spread_mean",
        "abs_current_mean",
        "duration_min",
        "soc_drop",
        "warn_duration_min",
        "stall_warn_minutes",
        "soc30_warn_minutes",
        "drive_temp_warn_minutes",
        "feature_outlier_ratio",
        "invalid_ratio",
    ]
    for battery_id, g in df.groupby("battery_id"):
        g = g.sort_values("flight_id").reset_index(drop=True)
        for i in range(1, len(g)):
            d_raw = float(g.loc[i, "d_raw_soh"])
            if not np.isfinite(d_raw) or abs(d_raw) < cfg.raw_jump_abs_threshold:
                continue
            pre = g.iloc[max(0, i - cfg.pre_window) : i]
            post = g.iloc[i + 1 : i + 1 + cfg.post_window]
            row = {
                "battery_id": str(battery_id),
                "chron_index": int(g.loc[i, "chron_index"]),
                "flight_id": int(g.loc[i, "flight_id"]),
                "source_folder": str(g.loc[i, "source_folder"]),
                "raw_soh_prev": float(g.loc[i - 1, "raw_soh_median_selected"]),
                "raw_soh_curr": float(g.loc[i, "raw_soh_median_selected"]),
                "d_raw_soh": d_raw,
                "d_norm_soh": float(g.loc[i, "d_norm_soh"]),
                "d_clean_soh": float(g.loc[i, "d_clean_soh"]),
                "gap_flight_id": float(g.loc[i, "gap_flight_id"]),
                "pre_mean_raw_soh": float(pre["raw_soh_median_selected"].mean()) if len(pre) else np.nan,
                "post_mean_raw_soh": float(post["raw_soh_median_selected"].mean()) if len(post) else np.nan,
                "persist_shift_10": (
                    float(post["raw_soh_median_selected"].mean() - pre["raw_soh_median_selected"].mean())
                    if len(pre) and len(post)
                    else np.nan
                ),
                "post_std_raw_soh": float(post["raw_soh_median_selected"].std(ddof=0)) if len(post) else np.nan,
            }
            for col in feature_cols:
                row[col] = float(g.loc[i, col]) if np.isfinite(g.loc[i, col]) else np.nan
                row[f"d_{col}"] = float(g.loc[i, f"d_{col}"]) if np.isfinite(g.loc[i, f"d_{col}"]) else np.nan
                if len(pre):
                    row[f"{col}_pre_mean"] = float(pre[col].mean())
                else:
                    row[f"{col}_pre_mean"] = np.nan
                if len(post):
                    row[f"{col}_post_mean"] = float(post[col].mean())
                else:
                    row[f"{col}_post_mean"] = np.nan
            rows.append(row)
    jumps = pd.DataFrame(rows)
    if jumps.empty:
        return jumps
    sync = jumps.groupby("flight_id")["battery_id"].nunique().rename("sync_both_batteries").reset_index()
    sync["sync_both_batteries"] = sync["sync_both_batteries"] >= 2
    jumps = jumps.merge(sync, on="flight_id", how="left")
    return jumps.sort_values(["flight_id", "battery_id"]).reset_index(drop=True)


def plot_raw_series(df: pd.DataFrame, jumps: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
    for ax, battery_id in zip(axes, ["1", "2"]):
        g = df[df["battery_id"] == battery_id].sort_values("flight_id")
        j = jumps[jumps["battery_id"] == battery_id]
        ax.plot(g["chron_index"], g["raw_soh_median_selected"], lw=1.2, color="#d62728", label="raw observed SOH")
        ax.plot(g["chron_index"], g["soh_observed_norm_flight"], lw=1.0, color="#1f77b4", alpha=0.8, label="normalized SOH")
        ax.scatter(j["chron_index"], j["raw_soh_curr"], color="#111111", s=20, zorder=3, label="raw jump" if battery_id == "1" else None)
        ax.set_ylabel("SOH (%)")
        ax.set_title(f"Battery {battery_id}: raw observed SOH vs normalized SOH")
        ax.grid(alpha=0.25)
        ax.legend(loc="best")
    axes[-1].set_xlabel("Chronological flight index")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def plot_top_correlations(corr_df: pd.DataFrame, out_path: Path) -> None:
    if corr_df.empty:
        return
    picks = (
        corr_df.sort_values("abs_spearman", ascending=False)
        .groupby("battery_id", as_index=False)
        .head(6)
        .copy()
    )
    if picks.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    for ax, battery_id in zip(axes, ["1", "2"]):
        g = picks[picks["battery_id"] == battery_id].sort_values("spearman")
        ax.barh(g["feature"], g["spearman"], color=["#d62728" if x < 0 else "#1f77b4" for x in g["spearman"]])
        ax.set_title(f"Battery {battery_id}: top Spearman with d_raw_soh")
        ax.set_xlabel("Spearman")
        ax.grid(alpha=0.25, axis="x")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def plot_jump_windows(df: pd.DataFrame, jumps: pd.DataFrame, out_path: Path, top_n: int) -> None:
    focus = (
        jumps.sort_values(["sync_both_batteries", "d_raw_soh"], ascending=[False, False], key=lambda s: np.abs(s))
        .drop_duplicates("flight_id")
        .head(top_n)
    )
    if focus.empty:
        return
    fig, axes = plt.subplots(len(focus), 1, figsize=(15, 4 * len(focus)), sharex=False)
    if len(focus) == 1:
        axes = [axes]
    for ax, (_, event) in zip(axes, focus.iterrows()):
        flight_id = int(event["flight_id"])
        win = df[(df["flight_id"] >= flight_id - 40) & (df["flight_id"] <= flight_id + 40)].copy()
        if win.empty:
            continue
        x = win["flight_id"]
        ax.plot(x, zscore(win["raw_soh_median_selected"]), color="#111111", lw=1.3, label="raw_soh")
        for col, color in [
            ("temp_avg_mean", "#d62728"),
            ("oat_mean", "#ff7f0e"),
            ("cap_est_mean", "#2ca02c"),
            ("kalman_gap_abs_mean", "#1f77b4"),
            ("volt_spread_mean", "#9467bd"),
        ]:
            ax.plot(x, zscore(win[col]), color=color, lw=1.0, alpha=0.9, label=col)
        ax.axvline(flight_id, color="#444444", linestyle="--", lw=1.0)
        ax.set_title(f"Jump window around flight {flight_id}")
        ax.set_ylabel("z-score")
        ax.grid(alpha=0.25)
    axes[-1].set_xlabel("Flight ID")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze raw observed SOH jumps against observed flight-level metrics to find "
            "temperature, estimator, warning, and data-quality trends behind persistent spikes."
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
        "--raw-root",
        type=Path,
        default=Path("data/raw_csv/by_plane/166"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("ml_workspace/SOH_normalized/output/observed_norm/plane_166/raw_soh_analysis"),
    )
    parser.add_argument("--raw-jump-abs-threshold", type=float, default=10.0)
    args = parser.parse_args()

    cfg = Config(
        labels_csv=args.labels_csv,
        feature_csv=args.feature_csv,
        raw_root=args.raw_root,
        out_dir=args.out_dir,
        raw_jump_abs_threshold=float(args.raw_jump_abs_threshold),
    )
    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    labels = pd.read_csv(cfg.labels_csv)
    labels["battery_id"] = labels["battery_id"].astype(str)
    features = pd.read_csv(cfg.feature_csv)
    features["battery_id"] = features["battery_id"].astype(str)

    keys = labels[["flight_id", "source_folder"]].drop_duplicates().sort_values("flight_id").reset_index(drop=True)
    warns = load_warn_features(cfg.raw_root, keys)

    merged = labels.merge(
        features,
        on=["flight_index", "flight_id", "source_folder", "battery_id"],
        how="left",
        validate="one_to_one",
    ).merge(
        warns,
        on=["flight_id", "source_folder"],
        how="left",
        validate="many_to_one",
    )

    merged = merged.sort_values(["battery_id", "flight_id"]).reset_index(drop=True)
    delta_base_cols = [
        "temp_avg_mean",
        "oat_mean",
        "cap_est_mean",
        "kalman_gap_abs_mean",
        "volt_spread_mean",
        "abs_current_mean",
        "duration_min",
        "soc_drop",
        "warn_duration_min",
        "stall_warn_minutes",
        "soc30_warn_minutes",
        "drive_temp_warn_minutes",
        "feature_outlier_ratio",
        "invalid_ratio",
    ]
    merged = add_deltas(merged, delta_base_cols)
    for battery_id, idx in merged.groupby("battery_id").groups.items():
        g = merged.loc[idx]
        for col in [f"d_{c}" for c in delta_base_cols]:
            merged.loc[g.index, f"z_{col}"] = zscore(g[col]).to_numpy()

    jumps = build_jump_table(merged, cfg)
    if not jumps.empty:
        jumps["reason_flags"] = jumps.apply(build_reason, axis=1)

    corr_features = [f"d_{c}" for c in delta_base_cols] + delta_base_cols
    corr_df = correlation_rows(merged, "d_raw_soh", corr_features)

    summary_rows: list[dict[str, float | int | str]] = []
    for battery_id, g in merged.groupby("battery_id"):
        g = g.sort_values("flight_id")
        jump_mask = g["d_raw_soh"].abs() >= cfg.raw_jump_abs_threshold
        summary_rows.append(
            {
                "battery_id": str(battery_id),
                "n_flights": int(len(g)),
                "raw_jump_abs_threshold": cfg.raw_jump_abs_threshold,
                "n_raw_jumps": int(jump_mask.sum()),
                "max_abs_raw_jump": float(g["d_raw_soh"].abs().max()),
                "raw_delta_std": float(g["d_raw_soh"].std(ddof=0)),
                "mean_abs_raw_jump": float(g.loc[jump_mask, "d_raw_soh"].abs().mean()) if jump_mask.any() else np.nan,
                "share_sync_jumps": (
                    float(jumps[(jumps["battery_id"] == str(battery_id)) & (jumps["sync_both_batteries"])]["flight_id"].nunique())
                    / float(jumps[jumps["battery_id"] == str(battery_id)]["flight_id"].nunique())
                    if not jumps.empty and jumps[jumps["battery_id"] == str(battery_id)]["flight_id"].nunique() > 0
                    else np.nan
                ),
            }
        )
    summary = pd.DataFrame(summary_rows)

    merged.to_csv(cfg.out_dir / "raw_soh_flight_diagnostics.csv", index=False)
    jumps.to_csv(cfg.out_dir / "raw_soh_jump_events.csv", index=False)
    corr_df.to_csv(cfg.out_dir / "raw_soh_jump_correlations.csv", index=False)
    summary.to_csv(cfg.out_dir / "raw_soh_analysis_summary.csv", index=False)

    plot_raw_series(merged, jumps, cfg.out_dir / "raw_soh_vs_normalized.png")
    plot_top_correlations(corr_df[corr_df["feature"].str.startswith("d_")], cfg.out_dir / "raw_jump_top_correlations.png")
    plot_jump_windows(merged, jumps, cfg.out_dir / "raw_jump_windows.png", cfg.top_plot_jumps)


if __name__ == "__main__":
    main()
