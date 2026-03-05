from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


def _map_pack_columns(pack_id: int) -> dict[str, str]:
    if pack_id not in (1, 2):
        raise ValueError(f"Unsupported pack_id: {pack_id}")
    p = str(pack_id)
    return {
        "observed_soh_pct": f" bat {p} soh",
        "current_a": f" bat {p} current",
        "voltage_v": f" bat {p} voltage",
        "soc_pct": f" bat {p} soc",
        "avg_cell_temp_c": f" bat {p} avg cell temp",
        "kalman_soc_pct": f" bat {p} kalman soc",
        "coulomb_soc_pct": f" bat {p} coulomb soc out",
        "cap_est_raw": f" bat {p} cap est",
        "flag_new_est_batt_cap_any": f" bat {p} cell flg new est batt cap",
        "flag_rst_coulomb_any": f" bat {p} cell flg rst coulomb",
    }


def _quantile_abs(values: np.ndarray, q: float) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.nan
    return float(np.nanquantile(np.abs(finite), q))


def _percentile(values: np.ndarray, q: float) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.nan
    return float(np.nanpercentile(finite, q))


def _iqr(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    if values.size == 0:
        return np.nan
    q75, q25 = np.nanpercentile(values, [75, 25])
    return float(q75 - q25)


def _span(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    if values.size == 0:
        return np.nan
    return float(np.nanmax(values) - np.nanmin(values))


def _p95_abs_derivative(series: pd.Series, dt_s: pd.Series, per_minute: bool = False) -> float:
    diffs = pd.to_numeric(series, errors="coerce").diff().to_numpy(dtype=float)
    dt = pd.to_numeric(dt_s, errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(diffs) & np.isfinite(dt) & (dt > 0)
    if not np.any(valid):
        return np.nan
    deriv = diffs[valid] / dt[valid]
    if per_minute:
        deriv = deriv * 60.0
    return _percentile(np.abs(deriv), 95.0)


def _event_type_for_row(frame: pd.DataFrame) -> pd.Series:
    event_type = np.where(
        frame["is_charging_event"].fillna(0).astype(int) == 1,
        "charge",
        np.where(frame["is_flight_event"].fillna(0).astype(int) == 1, "flight", "other"),
    )
    return pd.Series(event_type, index=frame.index, dtype="object")


def _load_pack_rows(dataset: ds.Dataset, plane_id: str, pack_id: int) -> pd.DataFrame:
    column_map = _map_pack_columns(pack_id)
    columns = [
        "plane_id",
        "flight_id",
        "event_datetime",
        "source_csv_kind",
        "source_pack_id",
        "is_charging_event",
        "is_flight_event",
        "time_ms",
        *column_map.values(),
    ]
    table = dataset.to_table(
        columns=columns,
        filter=(
            (ds.field("plane_id") == str(plane_id))
            & (ds.field("source_csv_kind") == "aux")
            & (ds.field("source_pack_id") == pack_id)
        ),
    )
    df = table.to_pandas()
    rename_map = {vendor: canonical for canonical, vendor in column_map.items()}
    df = df.rename(columns=rename_map)
    df["battery_id"] = pack_id
    return df


def load_aux_rows(timeseries_path: str | Path, plane_id: str) -> pd.DataFrame:
    dataset = ds.dataset(str(timeseries_path), format="parquet")
    frames = [_load_pack_rows(dataset, str(plane_id), pack_id) for pack_id in (1, 2)]
    out = pd.concat(frames, ignore_index=True)
    out["event_datetime"] = pd.to_datetime(out["event_datetime"], errors="coerce")
    numeric_cols = [
        "time_ms",
        "observed_soh_pct",
        "current_a",
        "voltage_v",
        "soc_pct",
        "avg_cell_temp_c",
        "kalman_soc_pct",
        "coulomb_soc_pct",
        "cap_est_raw",
        "flag_new_est_batt_cap_any",
        "flag_rst_coulomb_any",
    ]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["event_type"] = _event_type_for_row(out)
    out = out.sort_values(["battery_id", "event_datetime", "flight_id", "time_ms"]).reset_index(drop=True)
    return out


def _aggregate_one_event(event_df: pd.DataFrame) -> dict[str, object] | None:
    ordered = event_df.sort_values("time_ms").drop_duplicates(subset=["time_ms"], keep="first").copy()
    observed = ordered["observed_soh_pct"].dropna()
    if ordered.empty:
        return None
    event_type = ordered["event_type"].iloc[0]
    if event_type == "charge":
        current_limit = 45.0
        temp_low, temp_high = -2.0, 48.0
    else:
        current_limit = 130.0
        temp_low, temp_high = -2.0, 61.0

    valid = (
        ordered["time_ms"].notna()
        & ordered["current_a"].between(-current_limit, current_limit)
        & ordered["avg_cell_temp_c"].between(temp_low, temp_high)
        & ordered["soc_pct"].between(0.0, 100.0)
        & ordered["voltage_v"].between(200.0, 407.0)
    )
    valid_df = ordered.loc[valid].copy()
    n_valid = int(len(valid_df))

    row: dict[str, object] = {
        "plane_id": str(ordered["plane_id"].iloc[0]),
        "battery_id": int(ordered["battery_id"].iloc[0]),
        "flight_id": int(ordered["flight_id"].iloc[0]),
        "event_datetime": ordered["event_datetime"].iloc[0],
        "event_type": event_type,
        "observed_soh_pct": float(observed.median()) if not observed.empty else np.nan,
        "observed_soh_iqr_pct": _iqr(observed),
        "observed_soh_span_pct": _span(observed),
        "flag_new_est_batt_cap_any": int((ordered["flag_new_est_batt_cap_any"].fillna(0) > 0).any()),
        "flag_rst_coulomb_any": int((ordered["flag_rst_coulomb_any"].fillna(0) > 0).any()),
        "n_rows": n_valid,
        "event_duration_s": np.nan,
    }

    if n_valid == 0 and np.isnan(row["observed_soh_pct"]):
        return None

    if n_valid > 0:
        valid_df["dt_s"] = valid_df["time_ms"].diff().div(1000.0)
        event_duration_s = (valid_df["time_ms"].iloc[-1] - valid_df["time_ms"].iloc[0]) / 1000.0 if n_valid >= 2 else 0.0
        row["event_duration_s"] = float(max(event_duration_s, 0.0))
        gap = valid_df["kalman_soc_pct"] - valid_df["coulomb_soc_pct"]
        row.update(
            {
                "avg_cell_temp_mean_c": float(valid_df["avg_cell_temp_c"].mean()),
                "avg_cell_temp_min_c": float(valid_df["avg_cell_temp_c"].min()),
                "avg_cell_temp_max_c": float(valid_df["avg_cell_temp_c"].max()),
                "avg_cell_temp_span_c": _span(valid_df["avg_cell_temp_c"]),
                "current_abs_mean_a": float(valid_df["current_a"].abs().mean()),
                "p95_abs_current_a": _percentile(valid_df["current_a"].abs().to_numpy(dtype=float), 95.0),
                "current_span_a": _span(valid_df["current_a"]),
                "voltage_mean_v": float(valid_df["voltage_v"].mean()),
                "voltage_max_v": float(valid_df["voltage_v"].max()),
                "soc_mean_pct": float(valid_df["soc_pct"].mean()),
                "soc_min_pct": float(valid_df["soc_pct"].min()),
                "soc_max_pct": float(valid_df["soc_pct"].max()),
                "soc_span_pct": _span(valid_df["soc_pct"]),
                "kalman_coulomb_gap_mean_pct": float(gap.mean()) if gap.notna().any() else np.nan,
                "kalman_coulomb_gap_span_pct": _span(gap),
                "cap_est_delta_raw": float(valid_df["cap_est_raw"].iloc[-1] - valid_df["cap_est_raw"].iloc[0])
                if valid_df["cap_est_raw"].notna().sum() >= 2
                else np.nan,
                "cap_est_span_raw": _span(valid_df["cap_est_raw"]),
            }
        )
        if n_valid >= 10:
            row["p95_abs_dtemp_c_per_min"] = _p95_abs_derivative(valid_df["avg_cell_temp_c"], valid_df["dt_s"], per_minute=True)
            row["p95_abs_dcurrent_a_per_s"] = _p95_abs_derivative(valid_df["current_a"], valid_df["dt_s"], per_minute=False)
        else:
            row["p95_abs_dtemp_c_per_min"] = np.nan
            row["p95_abs_dcurrent_a_per_s"] = np.nan
    else:
        row.update(
            {
                "avg_cell_temp_mean_c": np.nan,
                "avg_cell_temp_min_c": np.nan,
                "avg_cell_temp_max_c": np.nan,
                "avg_cell_temp_span_c": np.nan,
                "p95_abs_dtemp_c_per_min": np.nan,
                "current_abs_mean_a": np.nan,
                "p95_abs_current_a": np.nan,
                "current_span_a": np.nan,
                "p95_abs_dcurrent_a_per_s": np.nan,
                "voltage_mean_v": np.nan,
                "voltage_max_v": np.nan,
                "soc_mean_pct": np.nan,
                "soc_min_pct": np.nan,
                "soc_max_pct": np.nan,
                "soc_span_pct": np.nan,
                "kalman_coulomb_gap_mean_pct": np.nan,
                "kalman_coulomb_gap_span_pct": np.nan,
                "cap_est_delta_raw": np.nan,
                "cap_est_span_raw": np.nan,
            }
        )

    return row


def build_event_observation_table(raw_df: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    del spec
    group_cols = ["plane_id", "battery_id", "flight_id", "event_datetime"]
    rows: list[dict[str, object]] = []
    for _, event_df in raw_df.groupby(group_cols, sort=True, observed=True):
        aggregated = _aggregate_one_event(event_df)
        if aggregated is not None:
            rows.append(aggregated)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["event_datetime"] = pd.to_datetime(out["event_datetime"], errors="coerce")
    out = out.sort_values(["battery_id", "event_datetime", "flight_id"]).reset_index(drop=True)
    return out
