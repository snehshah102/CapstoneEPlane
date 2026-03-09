from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    from .condition_noise import RT_PROFILES, compute_condition_scores, estimate_measurement_variance, resolve_rt_profile
    from .event_observation_dataset import build_event_observation_table, load_aux_rows
    from .residual_features import compute_residual_features
    from .spec_loader import load_plane_battery_spec
    from .state_space import add_monotone_projection, run_filterpy_smoother_1d
except ImportError:
    from condition_noise import RT_PROFILES, compute_condition_scores, estimate_measurement_variance, resolve_rt_profile
    from event_observation_dataset import build_event_observation_table, load_aux_rows
    from residual_features import compute_residual_features
    from spec_loader import load_plane_battery_spec
    from state_space import add_monotone_projection, run_filterpy_smoother_1d


def _json_default(value):
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def _ensure_output_dirs(base_output_dir: Path) -> dict[str, Path]:
    diagnostics = base_output_dir / "diagnostics"
    plots = diagnostics / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    return {"root": base_output_dir, "diagnostics": diagnostics, "plots": plots}


def _fit_one_battery(group: pd.DataFrame, q_day_sigma_pct: float) -> pd.DataFrame:
    fitted = run_filterpy_smoother_1d(group, q_day_sigma_pct=q_day_sigma_pct)
    fitted = add_monotone_projection(fitted)
    fitted["residual_pct"] = fitted["observed_soh_pct"] - fitted["latent_soh_smooth_pct"]
    fitted["standardized_residual"] = fitted["residual_pct"] / fitted["measurement_sigma_pct"]
    return fitted


def _condition_score_summary(latent_df: pd.DataFrame) -> pd.DataFrame:
    score_cols = [
        "score_current",
        "score_didt",
        "score_dtemp",
        "score_soc_edge",
        "score_observation_instability",
        "score_gap",
        "score_switch",
        "score_event_type",
        "score_missing",
        "condition_multiplier",
        "measurement_sigma_pct",
    ]
    rows: list[dict[str, object]] = []
    for (plane_id, battery_id), group in latent_df.groupby(["plane_id", "battery_id"], sort=False, observed=True):
        row: dict[str, object] = {
            "plane_id": str(plane_id),
            "battery_id": int(battery_id),
            "n_events": int(len(group)),
            "switch_event_count": int((group["score_switch"] > 0).sum()),
            "high_noise_event_count": int((group["condition_multiplier"] > 3.0).sum()),
        }
        for col in score_cols:
            values = group[col].dropna()
            row[f"{col}_p50"] = float(values.quantile(0.50)) if not values.empty else np.nan
            row[f"{col}_p90"] = float(values.quantile(0.90)) if not values.empty else np.nan
            row[f"{col}_p95"] = float(values.quantile(0.95)) if not values.empty else np.nan
            row[f"{col}_max"] = float(values.max()) if not values.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _series_summary(series: pd.Series) -> dict[str, float]:
    values = series.dropna()
    if values.empty:
        return {"total_variation": np.nan, "max_upward_jump": np.nan}
    diffs = values.diff().dropna()
    if diffs.empty:
        return {"total_variation": 0.0, "max_upward_jump": 0.0}
    return {
        "total_variation": float(diffs.abs().sum()),
        "max_upward_jump": float(diffs.max()),
    }


def _build_smoother_summary(
    plane_id: str,
    latent_df: pd.DataFrame,
    n_events_dropped_missing_observed_soh: int,
    q_day_sigma_pct: float,
    rt_profile: str,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "plane_id": str(plane_id),
        "rt_profile": str(rt_profile),
        "battery_ids_processed": sorted(int(v) for v in latent_df["battery_id"].unique()),
        "n_events_total": int(len(latent_df)),
        "n_events_per_battery": {},
        "n_events_dropped_missing_observed_soh": int(n_events_dropped_missing_observed_soh),
        "sigma_base_pct_per_battery": {},
        "q_day_sigma_pct": float(q_day_sigma_pct),
        "raw_total_variation_per_battery": {},
        "smoothed_total_variation_per_battery": {},
        "raw_max_upward_jump_pct_per_battery": {},
        "smoothed_max_upward_jump_pct_per_battery": {},
        "fraction_events_with_condition_multiplier_gt_3": {},
        "notes": "FilterPy latent SOH is the canonical output.",
    }
    for battery_id, group in latent_df.groupby("battery_id", sort=True, observed=True):
        raw_stats = _series_summary(group["observed_soh_pct"])
        smooth_stats = _series_summary(group["latent_soh_smooth_pct"])
        summary["n_events_per_battery"][str(int(battery_id))] = int(len(group))
        summary["sigma_base_pct_per_battery"][str(int(battery_id))] = float(group["sigma_base_pct"].iloc[0])
        summary["raw_total_variation_per_battery"][str(int(battery_id))] = raw_stats["total_variation"]
        summary["smoothed_total_variation_per_battery"][str(int(battery_id))] = smooth_stats["total_variation"]
        summary["raw_max_upward_jump_pct_per_battery"][str(int(battery_id))] = raw_stats["max_upward_jump"]
        summary["smoothed_max_upward_jump_pct_per_battery"][str(int(battery_id))] = smooth_stats["max_upward_jump"]
        summary["fraction_events_with_condition_multiplier_gt_3"][str(int(battery_id))] = float(
            (group["condition_multiplier"] > 3.0).mean()
        )
    return summary


def _build_spike_diagnostics(latent_df: pd.DataFrame, spike_threshold_pct: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    annotated_frames: list[pd.DataFrame] = []
    for _, group in latent_df.groupby(["plane_id", "battery_id"], sort=False, observed=True):
        g = group.sort_values(["event_datetime", "flight_id"]).copy()
        g["delta_observed_soh_pct"] = g["observed_soh_pct"].diff()
        g["delta_latent_soh_pct"] = g["latent_soh_smooth_pct"].diff()
        g["is_raw_upward_spike"] = g["delta_observed_soh_pct"] >= float(spike_threshold_pct)
        annotated_frames.append(g)
    annotated = pd.concat(annotated_frames, ignore_index=True)

    top_cols = [
        "plane_id",
        "battery_id",
        "flight_id",
        "event_datetime",
        "event_type",
        "delta_observed_soh_pct",
        "delta_latent_soh_pct",
        "observed_soh_pct",
        "latent_soh_smooth_pct",
        "residual_pct",
        "standardized_residual",
        "score_current",
        "score_didt",
        "score_dtemp",
        "score_soc_edge",
        "score_observation_instability",
        "score_gap",
        "score_switch",
        "score_event_type",
        "condition_multiplier",
        "measurement_sigma_pct",
        "flag_new_est_batt_cap_any",
        "flag_rst_coulomb_any",
        "kalman_coulomb_gap_mean_pct",
        "kalman_coulomb_gap_span_pct",
        "p95_abs_current_a",
        "p95_abs_dcurrent_a_per_s",
        "soc_min_pct",
        "soc_max_pct",
    ]
    top_spikes = annotated.loc[annotated["is_raw_upward_spike"]].sort_values(
        ["battery_id", "delta_observed_soh_pct"],
        ascending=[True, False],
    )[top_cols]

    summary_rows: list[dict[str, object]] = []
    feature_cols = [
        "score_current",
        "score_didt",
        "score_dtemp",
        "score_soc_edge",
        "score_observation_instability",
        "score_gap",
        "score_switch",
        "score_event_type",
        "condition_multiplier",
        "measurement_sigma_pct",
        "p95_abs_current_a",
        "p95_abs_dcurrent_a_per_s",
        "kalman_coulomb_gap_mean_pct",
        "kalman_coulomb_gap_span_pct",
    ]
    for (plane_id, battery_id), group in annotated.groupby(["plane_id", "battery_id"], sort=False, observed=True):
        for label, mask in [("spike", group["is_raw_upward_spike"]), ("non_spike", ~group["is_raw_upward_spike"].fillna(False))]:
            subset = group.loc[mask]
            row: dict[str, object] = {
                "plane_id": str(plane_id),
                "battery_id": int(battery_id),
                "group_type": label,
                "n_events": int(len(subset)),
                "charge_fraction": float(subset["event_type"].eq("charge").mean()) if len(subset) else np.nan,
                "flight_fraction": float(subset["event_type"].eq("flight").mean()) if len(subset) else np.nan,
                "other_fraction": float(subset["event_type"].eq("other").mean()) if len(subset) else np.nan,
                "new_est_flag_fraction": float((subset["flag_new_est_batt_cap_any"] > 0).mean()) if len(subset) else np.nan,
                "rst_coulomb_flag_fraction": float((subset["flag_rst_coulomb_any"] > 0).mean()) if len(subset) else np.nan,
            }
            for col in feature_cols:
                row[f"{col}_mean"] = float(subset[col].mean()) if len(subset) else np.nan
                row[f"{col}_median"] = float(subset[col].median()) if len(subset) else np.nan
            summary_rows.append(row)
    spike_summary = pd.DataFrame(summary_rows)
    return top_spikes.reset_index(drop=True), spike_summary


def _write_plots(latent_df: pd.DataFrame, plots_dir: Path) -> None:
    for battery_id, group in latent_df.groupby("battery_id", sort=True, observed=True):
        g = group.sort_values(["event_datetime", "flight_id"])

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(g["event_datetime"], g["observed_soh_pct"], color="0.7", linewidth=1.0, label="Observed SOH")
        ax.plot(g["event_datetime"], g["latent_soh_filter_pct"], color="#1f77b4", linewidth=1.1, label="FilterPy filter")
        ax.plot(g["event_datetime"], g["latent_soh_smooth_pct"], color="#d62728", linewidth=1.8, label="FilterPy RTS")
        band_low = g["latent_soh_smooth_pct"] - 2.0 * g["latent_soh_smooth_std_pct"]
        band_high = g["latent_soh_smooth_pct"] + 2.0 * g["latent_soh_smooth_std_pct"]
        ax.fill_between(g["event_datetime"], band_low, band_high, color="#d62728", alpha=0.15, linewidth=0)
        ax.set_title(f"Plane {g['plane_id'].iloc[0]} Battery {int(battery_id)}: Observed vs Latent SOH")
        ax.set_ylabel("SOH (%)")
        ax.legend(loc="best")
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(plots_dir / f"battery_{int(battery_id)}_raw_vs_smoothed.png", dpi=160)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(g["event_datetime"], g["measurement_sigma_pct"], color="#9467bd", linewidth=1.3)
        ax.set_title(f"Plane {g['plane_id'].iloc[0]} Battery {int(battery_id)}: Measurement Sigma")
        ax.set_ylabel("Measurement sigma (%)")
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(plots_dir / f"battery_{int(battery_id)}_measurement_sigma.png", dpi=160)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.hist(g["residual_pct"].dropna(), bins=30, color="#ff7f0e", alpha=0.85)
        ax.set_title(f"Plane {g['plane_id'].iloc[0]} Battery {int(battery_id)}: Residual Histogram")
        ax.set_xlabel("Observed - latent SOH (%)")
        fig.tight_layout()
        fig.savefig(plots_dir / f"battery_{int(battery_id)}_residual_hist.png", dpi=160)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.scatter(g["score_switch"], g["residual_pct"], alpha=0.55, s=14, color="#7f7f7f")
        ax.set_title(f"Plane {g['plane_id'].iloc[0]} Battery {int(battery_id)}: Residual vs switch score")
        ax.set_xlabel("score_switch")
        ax.set_ylabel("Observed - latent SOH (%)")
        fig.tight_layout()
        fig.savefig(plots_dir / f"battery_{int(battery_id)}_residual_vs_switch_score.png", dpi=160)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.scatter(g["score_observation_instability"], g["residual_pct"], alpha=0.55, s=14, color="#bcbd22")
        ax.set_title(f"Plane {g['plane_id'].iloc[0]} Battery {int(battery_id)}: Residual vs observation instability")
        ax.set_xlabel("score_observation_instability")
        ax.set_ylabel("Observed - latent SOH (%)")
        fig.tight_layout()
        fig.savefig(plots_dir / f"battery_{int(battery_id)}_residual_vs_instability.png", dpi=160)
        plt.close(fig)


def build_latent_soh_labels(
    plane_id: str,
    timeseries_path: str | Path,
    spec_path: str | Path,
    output_dir: str | Path,
    q_day_sigma_pct: float = 0.05,
    spike_threshold_pct: float = 2.0,
    rt_profile: str = "balanced",
) -> dict[str, object]:
    spec = load_plane_battery_spec(spec_path, plane_id)
    resolved_profile = resolve_rt_profile(rt_profile)
    dirs = _ensure_output_dirs(Path(output_dir))

    raw_df = load_aux_rows(timeseries_path=timeseries_path, plane_id=plane_id)
    event_df = build_event_observation_table(raw_df, spec=spec)
    event_df.to_csv(dirs["root"] / "event_observation_table.csv", index=False)

    with_observed = event_df["observed_soh_pct"].notna()
    n_dropped = int((~with_observed).sum())
    model_df = event_df.loc[with_observed].copy()
    if model_df.empty:
        raise ValueError(f"No observed SOH events available for plane {plane_id}")

    model_df = compute_condition_scores(model_df, spec=spec, spike_threshold_pct=spike_threshold_pct)
    model_df = estimate_measurement_variance(model_df, rt_profile=resolved_profile)

    fitted_frames: list[pd.DataFrame] = []
    for _, group in model_df.groupby(["plane_id", "battery_id"], sort=False, observed=True):
        fitted_frames.append(_fit_one_battery(group, q_day_sigma_pct=q_day_sigma_pct))
    latent_df = pd.concat(fitted_frames, ignore_index=True)
    latent_df = compute_residual_features(latent_df)
    latent_df = latent_df.sort_values(["battery_id", "event_datetime", "flight_id"]).reset_index(drop=True)
    latent_df.to_csv(dirs["root"] / "latent_soh_event_table.csv", index=False)

    condition_summary = _condition_score_summary(latent_df)
    condition_summary.to_csv(dirs["diagnostics"] / "condition_score_summary.csv", index=False)
    top_spikes, spike_summary = _build_spike_diagnostics(latent_df, spike_threshold_pct=spike_threshold_pct)
    top_spikes.to_csv(dirs["diagnostics"] / "top_raw_spike_events.csv", index=False)
    spike_summary.to_csv(dirs["diagnostics"] / "spike_feature_summary.csv", index=False)

    smoother_summary = _build_smoother_summary(
        plane_id=plane_id,
        latent_df=latent_df,
        n_events_dropped_missing_observed_soh=n_dropped,
        q_day_sigma_pct=q_day_sigma_pct,
        rt_profile=str(resolved_profile["name"]),
    )
    (dirs["diagnostics"] / "smoother_summary.json").write_text(
        json.dumps(smoother_summary, indent=2, default=_json_default),
        encoding="utf-8",
    )

    _write_plots(latent_df, plots_dir=dirs["plots"])

    return {
        "plane_id": str(plane_id),
        "rt_profile": str(resolved_profile["name"]),
        "output_dir": str(dirs["root"]),
        "event_observation_rows": int(len(event_df)),
        "latent_rows": int(len(latent_df)),
        "n_events_dropped_missing_observed_soh": n_dropped,
        "smoother_summary": smoother_summary,
    }


def _resolve_output_dir(output_dir: str | None, plane_id: str) -> Path:
    if output_dir:
        return Path(output_dir)
    return Path("ml_workspace") / "latent_soh" / "output" / f"plane_{plane_id}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build condition-aware latent SOH event labels")
    parser.add_argument("--plane-id", required=True, help="Plane identifier, e.g. 166")
    parser.add_argument(
        "--timeseries-path",
        default="data/event_timeseries.parquet",
        help="Path to event_timeseries parquet",
    )
    parser.add_argument(
        "--spec-path",
        default="ml_workspace/battery_specs.yaml",
        help="Path to plane battery spec yaml",
    )
    parser.add_argument("--output-dir", default=None, help="Optional output directory override")
    parser.add_argument("--q-day-sigma-pct", type=float, default=0.05, help="Daily process sigma for latent SOH")
    parser.add_argument(
        "--rt-profile",
        choices=sorted(RT_PROFILES),
        default="balanced",
        help="Named measurement-noise profile controlling R_t aggressiveness",
    )
    parser.add_argument(
        "--spike-threshold-pct",
        type=float,
        default=2.0,
        help="Reserved spike threshold for downstream diagnostics",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = build_latent_soh_labels(
        plane_id=str(args.plane_id),
        timeseries_path=args.timeseries_path,
        spec_path=args.spec_path,
        output_dir=_resolve_output_dir(args.output_dir, str(args.plane_id)),
        q_day_sigma_pct=float(args.q_day_sigma_pct),
        spike_threshold_pct=float(args.spike_threshold_pct),
        rt_profile=str(args.rt_profile),
    )
    print(json.dumps(result, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
