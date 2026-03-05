from __future__ import annotations

import numpy as np
import pandas as pd


def _time_rolling_feature(group: pd.DataFrame, value_col: str, window: str, agg: str) -> pd.Series:
    indexed = group.set_index("event_datetime")[value_col]
    rolled = getattr(indexed.rolling(window, min_periods=1), agg)()
    return rolled.reset_index(drop=True)


def compute_residual_features(latent_df: pd.DataFrame, event_window: int = 5, day_window: int = 30) -> pd.DataFrame:
    work = latent_df.sort_values(["battery_id", "event_datetime", "flight_id"]).copy()
    out_frames: list[pd.DataFrame] = []
    outlier_threshold = 2.0
    time_window = f"{int(day_window)}D"

    for _, group in work.groupby(["plane_id", "battery_id"], sort=False, observed=True):
        g = group.sort_values(["event_datetime", "flight_id"]).reset_index(drop=True).copy()
        resid = g["residual_pct"]
        abs_resid = resid.abs()
        g["resid_abs_mean_last_5_events"] = abs_resid.rolling(event_window, min_periods=1).mean()
        g["resid_std_last_5_events"] = resid.rolling(event_window, min_periods=1).std(ddof=0)
        g["resid_max_pos_last_5_events"] = resid.rolling(event_window, min_periods=1).max()
        g["resid_max_neg_last_5_events"] = resid.rolling(event_window, min_periods=1).min()
        g["resid_outlier_count_last_5_events"] = (
            (abs_resid > outlier_threshold).astype(int).rolling(event_window, min_periods=1).sum()
        )

        g["resid_abs_mean_last_30d"] = _time_rolling_feature(
            g.assign(residual_pct=g["residual_pct"].abs()), "residual_pct", time_window, "mean"
        )
        g["resid_std_last_30d"] = _time_rolling_feature(g, "residual_pct", time_window, "std").fillna(0.0)
        g["resid_outlier_count_last_30d"] = _time_rolling_feature(
            g.assign(_outlier=(abs_resid > outlier_threshold).astype(int)), "_outlier", time_window, "sum"
        )
        g["condition_multiplier_last_5_events_mean"] = g["condition_multiplier"].rolling(event_window, min_periods=1).mean()
        g["score_switch_last_5_events_sum"] = g["score_switch"].rolling(event_window, min_periods=1).sum()
        g["score_observation_instability_last_5_events_mean"] = (
            g["score_observation_instability"].rolling(event_window, min_periods=1).mean()
        )
        out_frames.append(g)

    out = pd.concat(out_frames, ignore_index=True)
    numeric_fill_zero = [
        "resid_std_last_5_events",
        "resid_std_last_30d",
    ]
    for col in numeric_fill_zero:
        out[col] = out[col].fillna(0.0)
    return out
