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
    jump_threshold: float = 15.0
    plateau_tol: float = 5.0
    prepost_window: int = 5


def normalize_col(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def load_warn_features(raw_root: Path, keys: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    for _, r in keys.iterrows():
        source_folder = str(r["source_folder"])
        flight_index = int(r["flight_index"])
        flight_id = int(r["flight_id"])
        wpath = raw_root / source_folder
        wfile = next((p for p in wpath.glob("*_warns.csv")), None)
        if wfile is None:
            rows.append(
                {
                    "flight_index": flight_index,
                    "flight_id": flight_id,
                    "source_folder": source_folder,
                    "warn_duration_min": np.nan,
                    "stall_warn_minutes": np.nan,
                    "soc30_warn_minutes": np.nan,
                    "drive_temp_warn_minutes": np.nan,
                }
            )
            continue

        df = pd.read_csv(wfile, skipinitialspace=True, low_memory=False)
        if df.empty:
            rows.append(
                {
                    "flight_index": flight_index,
                    "flight_id": flight_id,
                    "source_folder": source_folder,
                    "warn_duration_min": 0.0,
                    "stall_warn_minutes": 0.0,
                    "soc30_warn_minutes": 0.0,
                    "drive_temp_warn_minutes": 0.0,
                }
            )
            continue

        df = df.rename(columns={c: normalize_col(c) for c in df.columns})
        if "time(min)" not in df.columns:
            rows.append(
                {
                    "flight_index": flight_index,
                    "flight_id": flight_id,
                    "source_folder": source_folder,
                    "warn_duration_min": np.nan,
                    "stall_warn_minutes": np.nan,
                    "soc30_warn_minutes": np.nan,
                    "drive_temp_warn_minutes": np.nan,
                }
            )
            continue
        df["time(min)"] = pd.to_numeric(df["time(min)"], errors="coerce")
        df = df.dropna(subset=["time(min)"]).sort_values("time(min)").reset_index(drop=True)
        if df.empty:
            rows.append(
                {
                    "flight_index": flight_index,
                    "flight_id": flight_id,
                    "source_folder": source_folder,
                    "warn_duration_min": 0.0,
                    "stall_warn_minutes": 0.0,
                    "soc30_warn_minutes": 0.0,
                    "drive_temp_warn_minutes": 0.0,
                }
            )
            continue

        dt = df["time(min)"].diff().fillna(0.0).clip(lower=0.0, upper=2.0)
        stall = pd.to_numeric(df.get("stall warning", pd.Series(0, index=df.index)), errors="coerce").fillna(0.0)
        soc30 = pd.to_numeric(df.get("soc<30%", pd.Series(0, index=df.index)), errors="coerce").fillna(0.0)
        drive_temp = pd.to_numeric(df.get("drive high temp", pd.Series(0, index=df.index)), errors="coerce").fillna(0.0)

        rows.append(
            {
                "flight_index": flight_index,
                "flight_id": flight_id,
                "source_folder": source_folder,
                "warn_duration_min": float(df["time(min)"].iloc[-1] - df["time(min)"].iloc[0]),
                "stall_warn_minutes": float((dt * (stall > 0)).sum()),
                "soc30_warn_minutes": float((dt * (soc30 > 0)).sum()),
                "drive_temp_warn_minutes": float((dt * (drive_temp > 0)).sum()),
            }
        )
    return pd.DataFrame(rows)


def build_plateau_runs(g: pd.DataFrame, tol: float) -> pd.DataFrame:
    g = g.sort_values("flight_index").reset_index(drop=True).copy()
    runs: list[dict[str, float | int | str]] = []
    i = 0
    n = len(g)
    while i < n:
        level = float(g.loc[i, "soh_observed_norm_flight"])
        j = i + 1
        while j < n and abs(float(g.loc[j, "soh_observed_norm_flight"]) - level) <= tol:
            j += 1
        seg = g.iloc[i:j]
        runs.append(
            {
                "battery_id": str(g.loc[i, "battery_id"]),
                "start_flight_index": int(seg["flight_index"].iloc[0]),
                "end_flight_index": int(seg["flight_index"].iloc[-1]),
                "run_length": int(len(seg)),
                "level_anchor": level,
                "level_mean": float(seg["soh_observed_norm_flight"].mean()),
                "level_std": float(seg["soh_observed_norm_flight"].std(ddof=0)),
            }
        )
        i = j
    return pd.DataFrame(runs)


def find_jumps(g: pd.DataFrame, threshold: float) -> pd.DataFrame:
    g = g.sort_values("flight_index").reset_index(drop=True).copy()
    g["delta_norm"] = g["soh_observed_norm_flight"].diff()
    g["delta_raw_med"] = g["raw_soh_median_selected"].diff()
    g["gap_flight_index"] = g["flight_index"].diff()
    g["gap_flight_id"] = g["flight_id"].diff()
    jumps = g[g["delta_norm"].abs() >= threshold].copy()
    return jumps


def prepost_summary(g: pd.DataFrame, jump_row: pd.Series, w: int) -> dict[str, float | int | str]:
    idx = int(jump_row["flight_index"])
    pre = g[(g["flight_index"] < idx) & (g["flight_index"] >= idx - w)]
    post = g[(g["flight_index"] > idx) & (g["flight_index"] <= idx + w)]
    fields = [
        "temp_avg_mean",
        "oat_mean",
        "cap_est_mean",
        "kalman_gap_abs_mean",
        "volt_spread_mean",
        "duration_min",
        "soc_drop",
        "regime_climb_ratio",
        "regime_pattern_ratio",
        "stall_warn_minutes",
        "soc30_warn_minutes",
    ]
    row: dict[str, float | int | str] = {
        "battery_id": str(jump_row["battery_id"]),
        "flight_index": int(jump_row["flight_index"]),
        "flight_id": int(jump_row["flight_id"]),
        "delta_norm": float(jump_row["delta_norm"]),
        "delta_raw_med": float(jump_row.get("delta_raw_med", np.nan)),
        "gap_flight_index": float(jump_row.get("gap_flight_index", np.nan)),
        "gap_flight_id": float(jump_row.get("gap_flight_id", np.nan)),
        "pre_n": int(len(pre)),
        "post_n": int(len(post)),
    }
    for c in fields:
        row[f"{c}_pre_mean"] = float(pre[c].mean()) if len(pre) else np.nan
        row[f"{c}_post_mean"] = float(post[c].mean()) if len(post) else np.nan
        row[f"{c}_delta_post_pre"] = row[f"{c}_post_mean"] - row[f"{c}_pre_mean"] if np.isfinite(row[f"{c}_post_mean"]) and np.isfinite(row[f"{c}_pre_mean"]) else np.nan
    return row


def add_sync_flag(jumps_all: pd.DataFrame) -> pd.DataFrame:
    if jumps_all.empty:
        return jumps_all
    out = jumps_all.copy()
    sync_map = (
        out.groupby("flight_index")["battery_id"]
        .nunique()
        .rename("sync_both_batteries")
        .reset_index()
    )
    sync_map["sync_both_batteries"] = sync_map["sync_both_batteries"] >= 2
    out = out.merge(sync_map, on="flight_index", how="left")
    return out


def plot_soh_series(df: pd.DataFrame, jumps: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(15, 10), sharex=True)
    for ax, b in zip(axes, ["1", "2"]):
        g = df[df["battery_id"] == b].sort_values("flight_index")
        j = jumps[jumps["battery_id"] == b]
        ax.plot(g["flight_index"], g["soh_observed_norm_flight"], color="#1f77b4", lw=1.2, label="normalized SOH")
        ax.plot(g["flight_index"], g["raw_soh_median_selected"], color="#ff7f0e", lw=1.0, alpha=0.8, label="raw SOH median")
        for _, r in j.iterrows():
            ax.axvline(float(r["flight_index"]), color="#d62728", alpha=0.35, lw=1.0)
            ax.scatter([r["flight_index"]], [r["soh_observed_norm_flight"]], color="#d62728", s=22, zorder=3)
        ax.axvline(300, color="#555555", linestyle="--", lw=1.0)
        ax.set_title(f"Battery {b}: SOH level shifts and jumps")
        ax.set_ylabel("SOH (%)")
        ax.grid(alpha=0.25)
        ax.legend(loc="best")
    axes[-1].set_xlabel("Flight index")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_jump_vs_gap(jumps: pd.DataFrame, out_path: Path) -> None:
    if jumps.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 6))
    c = jumps["sync_both_batteries"].map({True: "#d62728", False: "#1f77b4"})
    ax.scatter(jumps["gap_flight_index"], jumps["delta_norm"].abs(), s=38, alpha=0.8, c=c)
    ax.set_xlabel("Gap in flight_index since previous labeled flight")
    ax.set_ylabel("|delta SOH| at jump")
    ax.set_title("Jump magnitude vs flight gap")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_jump_window_features(df: pd.DataFrame, jumps: pd.DataFrame, out_path: Path) -> None:
    focus = jumps[jumps["sync_both_batteries"]].sort_values("flight_index").drop_duplicates("flight_index")
    if focus.empty:
        focus = jumps.sort_values("flight_index").drop_duplicates("flight_index").head(5)
    rows = []
    for _, j in focus.iterrows():
        idx = int(j["flight_index"])
        win = df[(df["flight_index"] >= idx - 3) & (df["flight_index"] <= idx + 3)].copy()
        win["jump_flight_index"] = idx
        rows.append(win)
    if not rows:
        return
    x = pd.concat(rows, ignore_index=True)
    for col in ["temp_avg_mean", "oat_mean", "cap_est_mean", "kalman_gap_abs_mean", "volt_spread_mean"]:
        m = x[col].mean(skipna=True)
        s = x[col].std(skipna=True)
        if np.isfinite(s) and s > 1e-8:
            x[f"z_{col}"] = (x[col] - m) / s
        else:
            x[f"z_{col}"] = 0.0

    fig, ax = plt.subplots(figsize=(14, 7))
    for col, color in [
        ("z_temp_avg_mean", "#d62728"),
        ("z_oat_mean", "#ff7f0e"),
        ("z_cap_est_mean", "#2ca02c"),
        ("z_kalman_gap_abs_mean", "#1f77b4"),
        ("z_volt_spread_mean", "#9467bd"),
    ]:
        g = x.groupby("flight_index")[col].mean().reset_index()
        ax.plot(g["flight_index"], g[col], color=color, lw=1.2, label=col.replace("z_", ""))
    for idx in sorted(focus["flight_index"].unique()):
        ax.axvline(idx, color="#666666", alpha=0.35, lw=0.9)
    ax.axvline(300, color="#222222", linestyle="--", lw=1.0)
    ax.set_xlabel("Flight index")
    ax.set_ylabel("Standardized value (z)")
    ax.set_title("Feature behavior around large synchronized jumps")
    ax.grid(alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Deep analysis of persistent SOH jumps: event durations, warning signals, "
            "flight gaps, and pre/post feature shifts."
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
        default=Path("ml_workspace/SOH_normalized/output/observed_norm/plane_166/jump_root_cause"),
    )
    args = parser.parse_args()

    cfg = Config(
        labels_csv=args.labels_csv,
        feature_csv=args.feature_csv,
        raw_root=args.raw_root,
        out_dir=args.out_dir,
    )
    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    labels = pd.read_csv(cfg.labels_csv)
    features = pd.read_csv(cfg.feature_csv)
    labels["battery_id"] = labels["battery_id"].astype(str)
    features["battery_id"] = features["battery_id"].astype(str)

    keys = (
        labels[["flight_index", "flight_id", "source_folder"]]
        .drop_duplicates()
        .sort_values("flight_index")
        .reset_index(drop=True)
    )
    warn_feats = load_warn_features(cfg.raw_root, keys)

    df = labels.merge(
        features,
        on=["flight_index", "flight_id", "source_folder", "battery_id"],
        how="inner",
    ).merge(
        warn_feats,
        on=["flight_index", "flight_id", "source_folder"],
        how="left",
    ).sort_values(["battery_id", "flight_index"]).reset_index(drop=True)

    jump_rows = []
    prepost_rows = []
    plateau_rows = []
    for b, g in df.groupby("battery_id"):
        jumps = find_jumps(g, cfg.jump_threshold)
        jump_rows.append(jumps)
        for _, jr in jumps.iterrows():
            prepost_rows.append(prepost_summary(g, jr, cfg.prepost_window))
        plateau_rows.append(build_plateau_runs(g, cfg.plateau_tol))

    jumps_all = pd.concat(jump_rows, ignore_index=True) if jump_rows else pd.DataFrame()
    jumps_all = add_sync_flag(jumps_all)
    prepost_df = pd.DataFrame(prepost_rows)
    plateau_df = pd.concat(plateau_rows, ignore_index=True) if plateau_rows else pd.DataFrame()

    corr_rows = []
    if not jumps_all.empty:
        test_cols = [
            "gap_flight_index",
            "gap_flight_id",
            "delta_raw_med",
            "temp_avg_mean",
            "oat_mean",
            "cap_est_mean",
            "kalman_gap_abs_mean",
            "volt_spread_mean",
            "duration_min",
            "soc_drop",
            "stall_warn_minutes",
            "soc30_warn_minutes",
        ]
        for c in test_cols:
            x = pd.to_numeric(jumps_all[c], errors="coerce")
            y = pd.to_numeric(jumps_all["delta_norm"].abs(), errors="coerce")
            m = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
            if m.sum() >= 4:
                corr_rows.append(
                    {
                        "feature": c,
                        "n": int(m.sum()),
                        "pearson_r": float(x[m].corr(y[m], method="pearson")),
                        "spearman_r": float(x[m].corr(y[m], method="spearman")),
                    }
                )
    jump_corr_df = pd.DataFrame(corr_rows).sort_values("spearman_r", ascending=False) if corr_rows else pd.DataFrame()

    plot_soh_series(df, jumps_all, cfg.out_dir / "soh_with_jumps.png")
    plot_jump_vs_gap(jumps_all, cfg.out_dir / "jump_vs_gap.png")
    plot_jump_window_features(df, jumps_all, cfg.out_dir / "jump_feature_trends.png")

    df.to_csv(cfg.out_dir / "flight_level_diagnostics.csv", index=False)
    jumps_all.to_csv(cfg.out_dir / "jump_events.csv", index=False)
    prepost_df.to_csv(cfg.out_dir / "jump_prepost_summary.csv", index=False)
    plateau_df.to_csv(cfg.out_dir / "plateau_runs.csv", index=False)
    jump_corr_df.to_csv(cfg.out_dir / "jump_magnitude_correlations.csv", index=False)

    print(f"wrote: {cfg.out_dir}")
    print(f"n_rows: {len(df)}")
    print(f"n_jumps: {len(jumps_all)}")
    if not jumps_all.empty:
        print("jump_counts_by_battery:")
        print(jumps_all["battery_id"].value_counts().to_string())
    if not plateau_df.empty:
        long_runs = plateau_df.sort_values("run_length", ascending=False).head(10)
        print("longest_plateaus:")
        print(long_runs.to_string(index=False))


if __name__ == "__main__":
    main()
