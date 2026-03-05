from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd


def build_static_dummies(
    df: pd.DataFrame,
    categorical_cols: list[str],
    prefix_sep: str = "__",
) -> tuple[pd.DataFrame, list[str]]:
    if not categorical_cols:
        return df.copy(), []
    dummy_frames = []
    dummy_cols: list[str] = []
    for col in categorical_cols:
        if col not in df.columns:
            continue
        dummies = pd.get_dummies(df[col].fillna("unknown").astype(str), prefix=col, prefix_sep=prefix_sep, dtype=float)
        dummy_frames.append(dummies)
        dummy_cols.extend(dummies.columns.tolist())
    out = pd.concat([df.reset_index(drop=True), *[frame.reset_index(drop=True) for frame in dummy_frames]], axis=1)
    return out, dummy_cols


def _safe_corr(x: pd.Series, y: pd.Series, method: str) -> float:
    joint = pd.concat([pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")], axis=1).dropna()
    if len(joint) < 3:
        return np.nan
    if joint.iloc[:, 0].nunique(dropna=True) <= 1 or joint.iloc[:, 1].nunique(dropna=True) <= 1:
        return np.nan
    return float(joint.iloc[:, 0].corr(joint.iloc[:, 1], method=method))


def infer_feature_family(feature_name: str) -> str:
    if "__" in feature_name:
        return "static_categorical"
    if any(token in feature_name for token in ["arrhenius", "stress", "resistance_proxy", "voltage_sag", "time_above_40", "throughput"]):
        return "physics"
    if any(token in feature_name for token in ["_lag", "_diff", "_pct_change", "_rate_per_day", "_roll", "_ewm", "prev_", "rolling_"]):
        return "history"
    if feature_name.startswith("latent_") or feature_name.startswith("_filterpy"):
        return "latent"
    if feature_name in {"plane_id", "battery_id", "battery_id_str", "event_type"}:
        return "static"
    return "operating"


def rank_features_by_correlation(
    df: pd.DataFrame,
    feature_cols: list[str],
    next_level_col: str,
    delta_col: str,
    min_non_null: int = 25,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for col in feature_cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        non_null = int(series.notna().sum())
        unique = int(series.nunique(dropna=True))
        if non_null < min_non_null or unique <= 1:
            continue
        pearson_level = _safe_corr(series, df[next_level_col], "pearson")
        spearman_level = _safe_corr(series, df[next_level_col], "spearman")
        pearson_delta = _safe_corr(series, df[delta_col], "pearson")
        spearman_delta = _safe_corr(series, df[delta_col], "spearman")
        combined_score = (
            0.45 * np.nan_to_num(abs(spearman_delta), nan=0.0)
            + 0.30 * np.nan_to_num(abs(pearson_delta), nan=0.0)
            + 0.15 * np.nan_to_num(abs(spearman_level), nan=0.0)
            + 0.10 * np.nan_to_num(abs(pearson_level), nan=0.0)
        )
        rows.append(
            {
                "feature": col,
                "family": infer_feature_family(col),
                "non_null_rows": non_null,
                "missing_frac": float(1.0 - non_null / max(len(df), 1)),
                "n_unique": unique,
                "pearson_next_level": pearson_level,
                "spearman_next_level": spearman_level,
                "pearson_next_delta": pearson_delta,
                "spearman_next_delta": spearman_delta,
                "combined_score": float(combined_score),
            }
        )
    return pd.DataFrame(rows).sort_values("combined_score", ascending=False).reset_index(drop=True)


def prune_correlated_features(
    df: pd.DataFrame,
    ranked_features: pd.DataFrame,
    max_pairwise_corr: float = 0.92,
) -> pd.DataFrame:
    selected: list[str] = []
    selected_rows: list[pd.Series] = []
    for _, row in ranked_features.iterrows():
        col = row["feature"]
        candidate = pd.to_numeric(df[col], errors="coerce")
        keep = True
        for selected_col in selected:
            corr = _safe_corr(candidate, pd.to_numeric(df[selected_col], errors="coerce"), "spearman")
            if np.isfinite(corr) and abs(corr) >= max_pairwise_corr:
                keep = False
                break
        if keep:
            selected.append(col)
            selected_rows.append(row)
    return pd.DataFrame(selected_rows).reset_index(drop=True)


def select_feature_subset(
    df: pd.DataFrame,
    ranked_features: pd.DataFrame,
    top_k_total: int = 60,
    max_per_family: int = 18,
    min_combined_score: float = 0.03,
    max_pairwise_corr: float = 0.92,
) -> pd.DataFrame:
    eligible = ranked_features.loc[ranked_features["combined_score"] >= min_combined_score].copy()
    if eligible.empty:
        return eligible
    family_frames = []
    for _, fam_frame in eligible.groupby("family", sort=False):
        family_frames.append(fam_frame.head(max_per_family))
    candidate_pool = pd.concat(family_frames, ignore_index=True).sort_values("combined_score", ascending=False)
    pruned = prune_correlated_features(df, candidate_pool, max_pairwise_corr=max_pairwise_corr)
    return pruned.head(top_k_total).reset_index(drop=True)


def summarize_selection_by_family(selected_df: pd.DataFrame) -> pd.DataFrame:
    if selected_df.empty:
        return pd.DataFrame(columns=["family", "n_selected", "mean_score", "max_score"])
    return (
        selected_df.groupby("family", as_index=False)
        .agg(
            n_selected=("feature", "count"),
            mean_score=("combined_score", "mean"),
            max_score=("combined_score", "max"),
        )
        .sort_values(["n_selected", "mean_score"], ascending=[False, False])
        .reset_index(drop=True)
    )


def feature_name_metadata(feature_names: list[str]) -> pd.DataFrame:
    rows = []
    lag_pattern = re.compile(r"_lag(\d+)$")
    roll_pattern = re.compile(r"_roll(?:mean|std|min|max|slope)_(\d+)$")
    ewm_pattern = re.compile(r"_ewm(?:mean|std)_(\d+)$")
    diff_pattern = re.compile(r"_(diff|pct_change|rate_per_day)(\d+)$")
    for name in feature_names:
        rows.append(
            {
                "feature": name,
                "family": infer_feature_family(name),
                "lag_step": int(lag_pattern.search(name).group(1)) if lag_pattern.search(name) else np.nan,
                "roll_window": int(roll_pattern.search(name).group(1)) if roll_pattern.search(name) else np.nan,
                "ewm_span": int(ewm_pattern.search(name).group(1)) if ewm_pattern.search(name) else np.nan,
                "rate_step": int(diff_pattern.search(name).group(2)) if diff_pattern.search(name) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def save_selected_feature_bundle(
    output_dir: Path,
    ranked_df: pd.DataFrame,
    selected_df: pd.DataFrame,
    feature_groups: dict[str, list[str]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ranked_df.to_csv(output_dir / "ranked_candidate_features.csv", index=False)
    selected_df.to_csv(output_dir / "selected_candidate_features.csv", index=False)
    summary_df = summarize_selection_by_family(selected_df)
    summary_df.to_csv(output_dir / "selected_feature_family_summary.csv", index=False)

    selected_features = selected_df["feature"].tolist()
    selected_lookup = set(selected_features)
    rows = []
    for group_name, group_cols in feature_groups.items():
        for col in group_cols:
            rows.append({"group": group_name, "feature": col, "selected": col in selected_lookup})
    pd.DataFrame(rows).to_csv(output_dir / "feature_group_membership.csv", index=False)

    (output_dir / "selected_features.txt").write_text("\n".join(selected_features) + ("\n" if selected_features else ""))
