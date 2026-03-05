from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from filterpy.kalman import KalmanFilter
from pykalman import KalmanFilter as PyKalmanFilter
from sklearn.isotonic import IsotonicRegression


@dataclass
class BackendAgreement:
    plane_id: str
    battery_id: int
    compare_backend_enabled: bool
    n_events_compared: int
    median_abs_backend_delta_pct: float | None
    p95_abs_backend_delta_pct: float | None
    max_abs_backend_delta_pct: float | None


def _prepare_sequence(event_df: pd.DataFrame, q_day_sigma_pct: float) -> pd.DataFrame:
    work = event_df.sort_values(["event_datetime", "flight_id"]).reset_index(drop=True).copy()
    work["delta_days"] = (
        work["event_datetime"].diff().dt.total_seconds().div(86400.0).clip(lower=1e-4, upper=30.0)
    )
    work.loc[work.index[0], "delta_days"] = 1e-4
    work["process_var_pct2"] = (float(q_day_sigma_pct) ** 2) * work["delta_days"]
    return work


def _initial_state(observed: np.ndarray) -> tuple[float, float]:
    finite = observed[np.isfinite(observed)]
    if finite.size == 0:
        raise ValueError("No finite observed SOH values available for smoothing")
    return float(np.median(finite[: min(5, finite.size)])), 100.0


def run_filterpy_smoother_1d(event_df: pd.DataFrame, q_day_sigma_pct: float) -> pd.DataFrame:
    work = _prepare_sequence(event_df, q_day_sigma_pct=q_day_sigma_pct)
    z = work["observed_soh_pct"].to_numpy(dtype=float).reshape(-1, 1)
    r = work["measurement_var_pct2"].to_numpy(dtype=float)
    q = work["process_var_pct2"].to_numpy(dtype=float)
    x0, p0 = _initial_state(z.ravel())

    n = len(work)
    kf = KalmanFilter(dim_x=1, dim_z=1)
    kf.x = np.array([[x0]], dtype=float)
    kf.P = np.array([[p0]], dtype=float)
    kf.F = np.array([[1.0]], dtype=float)
    kf.H = np.array([[1.0]], dtype=float)
    kf.Q = np.array([[q[0]]], dtype=float)
    kf.R = np.array([[r[0]]], dtype=float)

    Fs = np.repeat(np.array([[[1.0]]]), n, axis=0)
    Hs = np.repeat(np.array([[[1.0]]]), n, axis=0)
    Qs = q.reshape(n, 1, 1)
    Rs = r.reshape(n, 1, 1)
    means, covariances, means_pred, covariances_pred = kf.batch_filter(z, Fs=Fs, Qs=Qs, Hs=Hs, Rs=Rs)
    smooth_x, smooth_p, _, _ = kf.rts_smoother(means, covariances, Fs=Fs, Qs=Qs)

    work["latent_soh_filterpy_filter_pct"] = means[:, 0, 0]
    work["latent_soh_filterpy_smooth_pct"] = smooth_x[:, 0, 0]
    work["latent_soh_filterpy_smooth_var_pct2"] = smooth_p[:, 0, 0]
    work["latent_soh_filterpy_smooth_std_pct"] = np.sqrt(np.clip(work["latent_soh_filterpy_smooth_var_pct2"], 0.0, None))
    work["latent_soh_filter_pct"] = work["latent_soh_filterpy_filter_pct"]
    work["latent_soh_smooth_pct"] = work["latent_soh_filterpy_smooth_pct"]
    work["latent_soh_smooth_var_pct2"] = work["latent_soh_filterpy_smooth_var_pct2"]
    work["latent_soh_smooth_std_pct"] = work["latent_soh_filterpy_smooth_std_pct"]
    work["_filterpy_pred_var_pct2"] = covariances_pred[:, 0, 0]
    work["_filterpy_pred_state_pct"] = means_pred[:, 0, 0]
    return work


def run_pykalman_smoother_1d(event_df: pd.DataFrame, q_day_sigma_pct: float) -> pd.DataFrame:
    work = _prepare_sequence(event_df, q_day_sigma_pct=q_day_sigma_pct)
    z = work["observed_soh_pct"].to_numpy(dtype=float).reshape(-1, 1)
    r = work["measurement_var_pct2"].to_numpy(dtype=float)
    q = work["process_var_pct2"].to_numpy(dtype=float)
    x0, p0 = _initial_state(z.ravel())
    n = len(work)
    if n == 1:
        work["latent_soh_pykalman_smooth_pct"] = z.ravel()
        work["latent_soh_pykalman_smooth_var_pct2"] = r
        return work

    F = np.repeat(np.array([[[1.0]]]), n - 1, axis=0)
    H = np.repeat(np.array([[[1.0]]]), n, axis=0)
    Q = q[1:].reshape(n - 1, 1, 1)
    R = r.reshape(n, 1, 1)
    kf = PyKalmanFilter(
        transition_matrices=F,
        observation_matrices=H,
        transition_covariance=Q,
        observation_covariance=R,
        initial_state_mean=np.array([x0], dtype=float),
        initial_state_covariance=np.array([[p0]], dtype=float),
    )
    means, covariances = kf.smooth(z)
    work["latent_soh_pykalman_smooth_pct"] = means[:, 0]
    work["latent_soh_pykalman_smooth_var_pct2"] = covariances[:, 0, 0]
    return work


def add_monotone_projection(event_df: pd.DataFrame) -> pd.DataFrame:
    work = event_df.copy()
    x = np.arange(len(work), dtype=float)
    y = work["latent_soh_smooth_pct"].to_numpy(dtype=float)
    iso = IsotonicRegression(increasing=False, out_of_bounds="clip")
    work["latent_soh_monotone_pct"] = iso.fit_transform(x, y)
    return work


def compare_backend_agreement(latent_df: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (plane_id, battery_id), group in latent_df.groupby(["plane_id", "battery_id"], sort=False, observed=True):
        delta = group["latent_soh_backend_abs_delta_pct"].dropna()
        rows.append(
            BackendAgreement(
                plane_id=str(plane_id),
                battery_id=int(battery_id),
                compare_backend_enabled=bool(delta.size),
                n_events_compared=int(delta.size),
                median_abs_backend_delta_pct=float(delta.median()) if delta.size else None,
                p95_abs_backend_delta_pct=float(delta.quantile(0.95)) if delta.size else None,
                max_abs_backend_delta_pct=float(delta.max()) if delta.size else None,
            ).__dict__
        )
    return rows
