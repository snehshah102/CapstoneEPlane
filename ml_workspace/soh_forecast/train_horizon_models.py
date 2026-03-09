from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from ml_workspace.soh_forecast.benchmarking import (
    build_full_and_common_metrics,
    build_truth_frame,
    combine_prediction_tables,
    gbdt_importance_frame,
    ridge_coefficient_frame,
    summarize_feature_correlation,
)
from ml_workspace.soh_forecast.common import ModelArtifacts, TargetSpec, find_repo_root, set_seed
from ml_workspace.soh_forecast.feature_pipeline import (
    add_forecast_features,
    assign_shared_splits,
    available_feature_sets,
    load_latent_dataset,
    make_multi_horizon_target_specs,
    split_frames_from_assigned,
)
from ml_workspace.soh_forecast.models.elastic_net_delta import train_elastic_net_delta
from ml_workspace.soh_forecast.models.gam_spline_delta import train_gam_spline_delta
from ml_workspace.soh_forecast.models.gru_sequence import train_gru_sequence
from ml_workspace.soh_forecast.models.hist_gbdt_delta import train_hist_gbdt_delta
from ml_workspace.soh_forecast.models.lstm_sequence import LSTMConfig, train_lstm_sequence
from ml_workspace.soh_forecast.models.naive_zero_delta import train_naive_zero_delta
from ml_workspace.soh_forecast.models.physics_hybrid_nn import PhysicsHybridConfig, train_physics_hybrid_nn
from ml_workspace.soh_forecast.models.physics_informed_nn import PhysicsInformedConfig, train_physics_informed_nn
from ml_workspace.soh_forecast.models.random_forest_delta import train_random_forest_delta
from ml_workspace.soh_forecast.models.ridge_delta import train_ridge_delta


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train multi-horizon SOH models and select best per horizon.")
    parser.add_argument("--primary-plane", default="166", help="Primary plane id for train/valid/test")
    parser.add_argument("--holdout-plane", default="192", help="Holdout plane id")
    parser.add_argument("--run-latent-pipeline", action="store_true", help="Regenerate latent SOH tables if missing")
    parser.add_argument("--rt-profile", default="current", help="Latent SOH rt_profile")
    parser.add_argument("--q-day-sigma-pct", type=float, default=0.10, help="Latent SOH process sigma")
    parser.add_argument("--train-frac", type=float, default=0.70, help="Train fraction")
    parser.add_argument("--valid-frac", type=float, default=0.10, help="Validation fraction")
    parser.add_argument("--lookback", type=int, default=20, help="Sequence model lookback window")
    parser.add_argument("--device", default="cpu", help="Torch device for sequence/physics models")
    parser.add_argument("--tune", action="store_true", help="Enable broader hyperparameter tuning")
    parser.add_argument(
        "--horizons",
        default="1,5,10,15,20",
        help="Comma-separated flight horizons (e.g. 1,5,10,15,20)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for metrics and predictions",
    )
    return parser.parse_args()


def _select_best_model(metrics: pd.DataFrame) -> dict[str, object] | None:
    if metrics.empty:
        return None
    valid = metrics.loc[metrics["eval_split"].eq("valid")].copy()
    if valid.empty:
        return None
    best = valid.sort_values(["level_mae", "delta_mae"]).iloc[0]
    return best.to_dict()


def _save_model(artifact: ModelArtifacts, output_dir: Path) -> str | None:
    model = artifact.model
    if model is None:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(model, torch.nn.Module):
        model_path = output_dir / f"{artifact.model_name}.pt"
        torch.save(
            {
                "state_dict": model.state_dict(),
                "feature_names": artifact.feature_names,
                "diagnostics": artifact.diagnostics,
            },
            model_path,
        )
        return str(model_path)
    try:
        import joblib

        model_path = output_dir / f"{artifact.model_name}.joblib"
        joblib.dump(
            {
                "model": model,
                "feature_names": artifact.feature_names,
                "diagnostics": artifact.diagnostics,
            },
            model_path,
        )
        return str(model_path)
    except Exception:
        return None


def main() -> None:
    args = _parse_args()
    set_seed(42)

    repo_root = find_repo_root(Path.cwd())
    output_root = Path(args.output_dir) if args.output_dir else (
        repo_root / "ml_workspace" / "soh_forecast" / "output" / f"multihorizon_runner_plane_{args.primary_plane}"
    )
    output_root.mkdir(parents=True, exist_ok=True)

    latent_df, summaries = load_latent_dataset(
        repo_root=repo_root,
        primary_plane=args.primary_plane,
        holdout_plane=args.holdout_plane,
        run_latent_pipeline=args.run_latent_pipeline,
        rt_profile=args.rt_profile,
        q_day_sigma_pct=args.q_day_sigma_pct,
    )
    forecast_df = add_forecast_features(latent_df)
    feature_sets = available_feature_sets(forecast_df)

    horizons = [int(v.strip()) for v in str(args.horizons).split(",") if v.strip()]
    horizon_configs = tuple(
        {"kind": "flight", "value": value, "label": f"flight_{value}", "title": f"Next {value} flights"}
        for value in horizons
    )
    target_specs = make_multi_horizon_target_specs(
        horizon_configs=horizon_configs,
        include_observed=False,
        include_latent=True,
    )

    shared_df = assign_shared_splits(
        forecast_df,
        primary_plane=args.primary_plane,
        holdout_plane=args.holdout_plane,
        train_frac=args.train_frac,
        valid_frac=args.valid_frac,
    )

    summary_rows = []
    best_config = {}

    for target_name, target_spec in target_specs.items():
        target_df = shared_df.loc[shared_df[target_spec.next_col].notna()].copy()
        split_frames = split_frames_from_assigned(target_df)
        if split_frames.train.empty or split_frames.valid.empty:
            summary_rows.append(
                {
                    "target": target_name,
                    "status": "skipped",
                    "reason": "insufficient train/valid rows",
                }
            )
            continue

        raw_features = feature_sets.get("raw", [])
        operating_features = feature_sets.get("operating", [])
        latent_features = feature_sets.get("latent", [])
        physics_features = feature_sets.get("physics", [])
        static_numeric_features = feature_sets.get("static_numeric", [])
        history_features = feature_sets.get("history", [])
        all_features_with_latent = list(
            dict.fromkeys(
                raw_features
                + operating_features
                + latent_features
                + physics_features
                + static_numeric_features
                + history_features
            )
        )
        all_features_no_latent = list(
            dict.fromkeys(
                raw_features
                + operating_features
                + physics_features
                + static_numeric_features
                + history_features
            )
        )

        seq_feature_candidates_no_latent = [
            "current_abs_mean_a",
            "p95_abs_current_a",
            "current_span_a",
            "avg_cell_temp_mean_c",
            "avg_cell_temp_min_c",
            "avg_cell_temp_max_c",
            "avg_cell_temp_span_c",
            "soc_mean_pct",
            "soc_min_pct",
            "soc_max_pct",
            "soc_span_pct",
            "event_duration_s",
            "delta_days",
            "event_efc",
            "event_ah",
            "cumulative_efc",
            "cumulative_ah",
            "cumulative_flight_count",
            "flight_event_flag",
            "charge_event_flag",
            "time_since_prev_event_days",
        ]
        seq_features_no_latent = [col for col in seq_feature_candidates_no_latent if col in target_df.columns]
        if len(seq_features_no_latent) < 3:
            seq_features_no_latent = list(dict.fromkeys(raw_features))

        seq_feature_candidates_with_latent = [
            "latent_soh_filter_pct",
            "latent_soh_filter_std_pct",
            "measurement_sigma_pct",
            "condition_multiplier",
            *seq_feature_candidates_no_latent,
        ]
        seq_features_with_latent = [
            col for col in seq_feature_candidates_with_latent if col in target_df.columns
        ]
        if len(seq_features_with_latent) < 3:
            seq_features_with_latent = list(dict.fromkeys(raw_features + latent_features))

        corr_df = summarize_feature_correlation(target_df, all_features_with_latent, target_spec)

        if args.tune:
            ridge_alphas = [0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 300.0]
            elastic_grid = [
                {"alpha": alpha, "l1_ratio": l1_ratio, "max_iter": 50000, "tol": 1e-3, "selection": "random", "random_state": 42}
                for alpha in [0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
                for l1_ratio in [0.1, 0.3, 0.5, 0.7, 0.9]
            ]
            gbdt_grid = [
                {"learning_rate": 0.02, "max_depth": 3, "max_iter": 500, "min_samples_leaf": 10, "random_state": 42},
                {"learning_rate": 0.03, "max_depth": 3, "max_iter": 700, "min_samples_leaf": 8, "random_state": 42},
                {"learning_rate": 0.05, "max_depth": 4, "max_iter": 400, "min_samples_leaf": 8, "random_state": 42},
                {"learning_rate": 0.08, "max_depth": 4, "max_iter": 300, "min_samples_leaf": 5, "random_state": 42},
            ]
            rf_grid = [
                {"n_estimators": 400, "max_depth": None, "min_samples_leaf": 3, "max_features": "sqrt", "random_state": 42, "n_jobs": -1},
                {"n_estimators": 600, "max_depth": 10, "min_samples_leaf": 3, "max_features": "sqrt", "random_state": 42, "n_jobs": -1},
                {"n_estimators": 800, "max_depth": 12, "min_samples_leaf": 5, "max_features": 0.5, "random_state": 42, "n_jobs": -1},
            ]
            gam_alphas = [0.001, 0.01, 0.1, 1.0, 10.0]
            gam_knots = [3, 4, 5]
            seq_config_grid = [
                LSTMConfig(lookback=args.lookback, hidden_dim=48, dropout=0.1, lr=1e-3, device=args.device),
                LSTMConfig(lookback=30, hidden_dim=48, dropout=0.1, lr=5e-4, device=args.device),
                LSTMConfig(lookback=args.lookback, hidden_dim=32, dropout=0.2, lr=1e-3, device=args.device),
                LSTMConfig(lookback=30, hidden_dim=32, dropout=0.2, lr=5e-4, device=args.device),
            ]
            hybrid_configs = [
                PhysicsHybridConfig(hidden_dim=64, physics_hidden_dim=48, lr=1e-3, weight_decay=1e-4, device=args.device),
                PhysicsHybridConfig(hidden_dim=96, physics_hidden_dim=64, lr=5e-4, weight_decay=3e-4, device=args.device),
            ]
            pinn_configs = [
                PhysicsInformedConfig(hidden_dim=96, lr=1e-3, weight_decay=1e-5, device=args.device),
                PhysicsInformedConfig(hidden_dim=128, lr=5e-4, weight_decay=3e-5, device=args.device),
            ]
        else:
            ridge_alphas = None
            elastic_grid = None
            gbdt_grid = None
            rf_grid = None
            gam_alphas = None
            gam_knots = None
            seq_config_grid = [LSTMConfig(lookback=args.lookback, device=args.device)]
            hybrid_configs = [PhysicsHybridConfig(device=args.device)]
            pinn_configs = [PhysicsInformedConfig(device=args.device)]

        artifacts = [
            train_naive_zero_delta(split_frames, target_spec),
            train_ridge_delta(split_frames, target_spec, raw_features, model_name="ridge_raw_only", alphas=ridge_alphas),
            train_ridge_delta(split_frames, target_spec, raw_features + latent_features, model_name="ridge_raw_plus_latent", alphas=ridge_alphas),
            train_ridge_delta(split_frames, target_spec, raw_features, model_name="ridge_raw_only_no_latent", alphas=ridge_alphas),
            train_elastic_net_delta(
                split_frames,
                target_spec,
                all_features_with_latent,
                model_name="elastic_with_latent",
                grid=elastic_grid,
            ),
            train_elastic_net_delta(
                split_frames,
                target_spec,
                all_features_no_latent,
                model_name="elastic_no_latent",
                grid=elastic_grid,
            ),
            train_ridge_delta(
                split_frames,
                target_spec,
                all_features_with_latent,
                model_name="ridge_with_latent",
                alphas=ridge_alphas,
            ),
            train_ridge_delta(
                split_frames,
                target_spec,
                all_features_no_latent,
                model_name="ridge_no_latent",
                alphas=ridge_alphas,
            ),
            train_hist_gbdt_delta(
                split_frames,
                target_spec,
                all_features_with_latent,
                model_name="gbdt_with_latent",
                param_grid=gbdt_grid,
            ),
            train_hist_gbdt_delta(
                split_frames,
                target_spec,
                all_features_no_latent,
                model_name="gbdt_no_latent",
                param_grid=gbdt_grid,
            ),
            train_random_forest_delta(
                split_frames,
                target_spec,
                all_features_with_latent,
                model_name="random_forest_with_latent",
                param_grid=rf_grid,
            ),
            train_random_forest_delta(
                split_frames,
                target_spec,
                all_features_no_latent,
                model_name="random_forest_no_latent",
                param_grid=rf_grid,
            ),
            train_gam_spline_delta(
                split_frames,
                target_spec,
                all_features_with_latent,
                model_name="gam_spline_with_latent",
                alphas=gam_alphas,
                n_knots_list=gam_knots,
            ),
            train_gam_spline_delta(
                split_frames,
                target_spec,
                all_features_no_latent,
                model_name="gam_spline_no_latent",
                alphas=gam_alphas,
                n_knots_list=gam_knots,
            ),
        ]

        for idx, cfg in enumerate(seq_config_grid):
            suffix = f"_tune{idx}" if args.tune else ""
            artifacts.append(
                train_lstm_sequence(
                    target_df,
                    split_frames,
                    target_spec,
                    seq_features_with_latent,
                    model_name=f"lstm_sequence_with_latent{suffix}",
                    config=cfg,
                )
            )
            artifacts.append(
                train_gru_sequence(
                    target_df,
                    split_frames,
                    target_spec,
                    seq_features_with_latent,
                    model_name=f"gru_sequence_with_latent{suffix}",
                    config=cfg,
                )
            )
            artifacts.append(
                train_lstm_sequence(
                    target_df,
                    split_frames,
                    target_spec,
                    seq_features_no_latent,
                    model_name=f"lstm_sequence_no_latent{suffix}",
                    config=cfg,
                )
            )
            artifacts.append(
                train_gru_sequence(
                    target_df,
                    split_frames,
                    target_spec,
                    seq_features_no_latent,
                    model_name=f"gru_sequence_no_latent{suffix}",
                    config=cfg,
                )
            )

        for idx, cfg in enumerate(hybrid_configs):
            suffix = f"_tune{idx}" if args.tune else ""
            artifacts.append(
                train_physics_hybrid_nn(
                    split_frames,
                    target_spec,
                    all_features_with_latent,
                    model_name=f"physics_hybrid_with_latent{suffix}",
                    config=cfg,
                )
            )
            artifacts.append(
                train_physics_hybrid_nn(
                    split_frames,
                    target_spec,
                    all_features_no_latent,
                    model_name=f"physics_hybrid_no_latent{suffix}",
                    config=cfg,
                )
            )

        for idx, cfg in enumerate(pinn_configs):
            suffix = f"_tune{idx}" if args.tune else ""
            artifacts.append(
                train_physics_informed_nn(
                    split_frames,
                    target_spec,
                    all_features_with_latent,
                    model_name=f"physics_informed_with_latent{suffix}",
                    config=cfg,
                )
            )
            artifacts.append(
                train_physics_informed_nn(
                    split_frames,
                    target_spec,
                    all_features_no_latent,
                    model_name=f"physics_informed_no_latent{suffix}",
                    config=cfg,
                )
            )

        artifacts_by_name = {artifact.model_name: artifact for artifact in artifacts}
        model_metrics = pd.concat([artifact.metrics for artifact in artifacts if not artifact.metrics.empty], ignore_index=True)
        predictions = combine_prediction_tables(artifacts)
        truth_frame = build_truth_frame(target_df, target_spec)
        benchmark_df = truth_frame.merge(predictions, on=["event_id", "split"], how="left")

        comparison_models = list(artifacts_by_name.keys())
        full_available_metrics, common_subset_metrics, _ = build_full_and_common_metrics(
            benchmark_df,
            target_spec,
            comparison_models,
        )

        target_output_dir = output_root / target_spec.name
        target_output_dir.mkdir(parents=True, exist_ok=True)
        benchmark_df.to_csv(target_output_dir / f"{target_spec.name}_predictions.csv", index=False)
        model_metrics.to_csv(target_output_dir / f"{target_spec.name}_metrics_all_rows.csv", index=False)
        full_available_metrics.to_csv(target_output_dir / f"{target_spec.name}_metrics_by_available_predictions.csv", index=False)
        common_subset_metrics.to_csv(target_output_dir / f"{target_spec.name}_metrics_common_subset.csv", index=False)
        corr_df.to_csv(target_output_dir / f"{target_spec.name}_feature_correlations.csv", index=False)
        ridge_with_latent = artifacts_by_name.get("ridge_with_latent")
        gbdt_with_latent = artifacts_by_name.get("gbdt_with_latent")
        if ridge_with_latent is not None:
            ridge_coef_df = ridge_coefficient_frame(ridge_with_latent)
            ridge_coef_df.to_csv(target_output_dir / f"{target_spec.name}_ridge_coefficients_with_latent.csv", index=False)
        if gbdt_with_latent is not None:
            gbdt_importance_df = gbdt_importance_frame(gbdt_with_latent)
            gbdt_importance_df.to_csv(target_output_dir / f"{target_spec.name}_gbdt_importance_with_latent.csv", index=False)

        best_row = _select_best_model(model_metrics)
        best_model_name = best_row["model"] if best_row else None
        best_model_path = None
        if best_model_name:
            best_model_path = _save_model(artifacts_by_name[best_model_name], target_output_dir / "best_model")
        summary_rows.append(
            {
                "target": target_name,
                "best_model": best_model_name,
                "best_model_path": best_model_path,
                **(best_row or {}),
            }
        )
        if best_model_name:
            best_config[target_name] = {
                "model": best_model_name,
                "target": target_name,
                "next_col": target_spec.next_col,
                "delta_col": target_spec.delta_col,
                "metrics": best_row,
                "model_path": best_model_path,
            }

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(output_root / "best_models_by_horizon.csv", index=False)
    (output_root / "best_models_by_horizon.json").write_text(json.dumps(best_config, indent=2), encoding="utf-8")
    (output_root / "run_metadata.json").write_text(
        json.dumps(
            {
                "primary_plane": args.primary_plane,
                "holdout_plane": args.holdout_plane,
                "rt_profile": args.rt_profile,
                "q_day_sigma_pct": args.q_day_sigma_pct,
                "train_frac": args.train_frac,
                "valid_frac": args.valid_frac,
                "lookback": args.lookback,
                "device": args.device,
                "horizons": horizons,
                "output_dir": str(output_root),
                "latent_summaries": summaries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("Finished. Best models summary:")
    print(summary_df)


if __name__ == "__main__":
    main()
