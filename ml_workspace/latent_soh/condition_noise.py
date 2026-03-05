from __future__ import annotations

import math
from copy import deepcopy

import numpy as np
import pandas as pd


RT_PROFILES: dict[str, dict[str, object]] = {
    "current": {
        "sigma_base_fallback_pct": 0.75,
        "weights": {
            "score_current": 1.0,
            "score_didt": 0.75,
            "score_dtemp": 0.5,
            "score_soc_edge": 0.5,
            "score_observation_instability": 1.0,
            "score_gap": 0.75,
            "score_switch": 1.0,
            "score_event_type": 0.75,
            "score_missing": 0.5,
        },
    },
    "balanced": {
        "sigma_base_fallback_pct": 0.55,
        "weights": {
            "score_current": 0.5,
            "score_didt": 0.4,
            "score_dtemp": 0.25,
            "score_soc_edge": 0.15,
            "score_observation_instability": 0.8,
            "score_gap": 0.3,
            "score_switch": 0.6,
            "score_event_type": 0.2,
            "score_missing": 0.25,
        },
    },
    "light": {
        "sigma_base_fallback_pct": 0.45,
        "weights": {
            "score_current": 0.35,
            "score_didt": 0.25,
            "score_dtemp": 0.15,
            "score_soc_edge": 0.1,
            "score_observation_instability": 0.6,
            "score_gap": 0.2,
            "score_switch": 0.5,
            "score_event_type": 0.1,
            "score_missing": 0.2,
        },
    },
    "instability_focused": {
        "sigma_base_fallback_pct": 0.5,
        "weights": {
            "score_current": 0.25,
            "score_didt": 0.2,
            "score_dtemp": 0.1,
            "score_soc_edge": 0.1,
            "score_observation_instability": 1.0,
            "score_gap": 0.2,
            "score_switch": 0.8,
            "score_event_type": 0.15,
            "score_missing": 0.2,
        },
    },
}


def resolve_rt_profile(profile_name: str | None = None) -> dict[str, object]:
    name = str(profile_name or "balanced")
    profile = RT_PROFILES.get(name)
    if profile is None:
        supported = ", ".join(sorted(RT_PROFILES))
        raise KeyError(f"Unknown R_t profile '{name}'. Supported profiles: {supported}")
    resolved = deepcopy(profile)
    resolved["name"] = name
    return resolved


def _clip(series: pd.Series | np.ndarray, low: float, high: float) -> pd.Series:
    return pd.Series(series, copy=False).clip(lower=low, upper=high)


def compute_condition_scores(event_df: pd.DataFrame, spec: dict[str, object], spike_threshold_pct: float = 2.0) -> pd.DataFrame:
    del spike_threshold_pct
    work = event_df.copy()
    denom = np.where(work["event_type"].eq("charge"), float(spec["max_charge_a"]), float(spec["max_discharge_a"]))
    work["score_current"] = _clip(work["p95_abs_current_a"] / denom, 0.0, 2.0)
    work["score_didt"] = _clip(np.log1p(work["p95_abs_dcurrent_a_per_s"]) / math.log1p(20.0), 0.0, 2.0)
    work["score_dtemp"] = _clip(np.log1p(work["p95_abs_dtemp_c_per_min"]) / math.log1p(1.0), 0.0, 2.0)
    low_edge = _clip((10.0 - work["soc_min_pct"]) / 10.0, 0.0, 1.0)
    high_edge = _clip((work["soc_max_pct"] - 90.0) / 10.0, 0.0, 1.0)
    work["score_soc_edge"] = low_edge + high_edge
    work["score_observation_instability"] = _clip(work["observed_soh_iqr_pct"] / 1.0, 0.0, 3.0)
    score_gap_mean = _clip(work["kalman_coulomb_gap_mean_pct"].abs() / 5.0, 0.0, 2.0)
    score_gap_span = _clip(work["kalman_coulomb_gap_span_pct"] / 2.0, 0.0, 2.0)
    work["score_gap"] = score_gap_mean + score_gap_span
    work["score_switch"] = (
        1.0 * work["flag_new_est_batt_cap_any"].fillna(0.0).astype(float)
        + 0.5 * work["flag_rst_coulomb_any"].fillna(0.0).astype(float)
    )
    work["score_event_type"] = work["event_type"].map({"charge": 0.75, "other": 0.25, "flight": 0.0}).fillna(0.25)

    missing_fields = [
        "p95_abs_current_a",
        "p95_abs_dcurrent_a_per_s",
        "p95_abs_dtemp_c_per_min",
        "soc_min_pct",
        "soc_max_pct",
    ]
    work["score_missing"] = _clip(work[missing_fields].isna().sum(axis=1) * 0.5, 0.0, 2.0)
    return work


def _estimate_sigma_base_for_group(group: pd.DataFrame, sigma_base_fallback_pct: float) -> float:
    low_stress = (
        (group["score_current"] <= 0.25)
        & (group["score_didt"] <= 0.25)
        & (group["score_dtemp"] <= 0.25)
        & (group["score_soc_edge"] == 0.0)
        & (group["score_switch"] == 0.0)
        & (group["score_event_type"] <= 0.25)
        & (group["score_observation_instability"] <= 0.5)
    )
    subset = group.loc[low_stress].sort_values(["event_datetime", "flight_id"])
    if len(subset) < 30:
        return float(sigma_base_fallback_pct)
    delta = subset["observed_soh_pct"].diff().dropna().to_numpy(dtype=float)
    if delta.size == 0:
        return float(sigma_base_fallback_pct)
    med = float(np.median(delta))
    mad = float(np.median(np.abs(delta - med)))
    sigma = 1.4826 * mad / math.sqrt(2.0)
    return float(max(0.25, sigma))


def estimate_measurement_variance(event_df: pd.DataFrame, rt_profile: str | dict[str, object] | None = None) -> pd.DataFrame:
    work = event_df.copy()
    profile = resolve_rt_profile(rt_profile) if not isinstance(rt_profile, dict) else deepcopy(rt_profile)
    weights = dict(profile["weights"])
    sigma_base_fallback_pct = float(profile["sigma_base_fallback_pct"])
    sigma_map: dict[tuple[str, int], float] = {}
    for key, group in work.groupby(["plane_id", "battery_id"], sort=False, observed=True):
        sigma_map[(str(key[0]), int(key[1]))] = _estimate_sigma_base_for_group(
            group,
            sigma_base_fallback_pct=sigma_base_fallback_pct,
        )

    work["sigma_base_pct"] = [
        sigma_map[(str(plane_id), int(battery_id))]
        for plane_id, battery_id in zip(work["plane_id"], work["battery_id"])
    ]
    work["rt_profile"] = str(profile.get("name", "custom"))
    work["condition_multiplier"] = 1.0
    for score_name, weight in weights.items():
        work["condition_multiplier"] = work["condition_multiplier"] + float(weight) * work[score_name].fillna(0.0)
    work["measurement_sigma_pct_raw"] = work["sigma_base_pct"] * work["condition_multiplier"]
    work["measurement_sigma_pct"] = work["measurement_sigma_pct_raw"].clip(lower=0.25, upper=10.0)
    work["measurement_var_pct2"] = work["measurement_sigma_pct"] ** 2
    return work
