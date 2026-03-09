from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


EVTOL_PROTOCOLS = {
    "VAH01": "Baseline",
    "VAH02": "Extended cruise (1000 sec)",
    "VAH05": "10% power reduction during discharge",
    "VAH06": "CC charge current reduced to C/2",
    "VAH07": "CV charge voltage reduced to 4.0V",
    "VAH09": "Thermal chamber temperature 20C",
    "VAH10": "Thermal chamber temperature 30C",
    "VAH11": "20% power reduction during discharge",
    "VAH12": "Short cruise length (400 sec)",
    "VAH13": "Short cruise length (600 sec)",
    "VAH15": "Extended cruise (1000 sec)",
    "VAH16": "CC charge current reduced to 1.5C",
    "VAH17": "Baseline",
    "VAH20": "Charge current reduced to 1.5C",
    "VAH22": "Extended cruise (1000 sec)",
    "VAH23": "CV charge voltage reduced to 4.1V",
    "VAH24": "CC charge current reduced to C/2",
    "VAH25": "Thermal chamber temperature 20C",
    "VAH26": "Short cruise length (600 sec)",
    "VAH27": "Baseline",
    "VAH28": "10% power reduction during discharge",
    "VAH30": "Thermal chamber temperature 35C",
}

CAPACITY_TEST_NS_THRESHOLD = 9

SHARED_FEATURES = [
    "current_soh_pct",
    "latent_soh_filter_pct",
    "current_abs_mean_a",
    "p95_abs_current_a",
    "current_span_a",
    "avg_cell_temp_mean_c",
    "avg_cell_temp_max_c",
    "avg_cell_temp_span_c",
    "soc_span_pct",
    "event_duration_s",
    "delta_days",
    "event_efc",
    "event_ah",
    "cumulative_efc",
    "cumulative_ah",
    "cumulative_flight_count",
    "time_since_prev_event_days",
]


def find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "ml_workspace").exists() and (candidate / "data").exists():
            return candidate
    raise RuntimeError("Could not locate repo root from current working directory")


def _num(series_or_value, default: float = 0.0):
    series = pd.to_numeric(series_or_value, errors="coerce")
    if hasattr(series, "fillna"):
        return series.fillna(default)
    return default if pd.isna(series) else series


def build_evtol_pretrain_dataset(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    interval_rows: list[dict[str, object]] = []
    anchor_frames: list[pd.DataFrame] = []
    for path in sorted(root.glob("VAH*.csv")):
        if path.name.endswith("_impedance.csv"):
            continue

        raw = pd.read_csv(
            path,
            usecols=["time_s", "I_mA", "QCharge_mA_h", "QDischarge_mA_h", "Temperature__C", "cycleNumber", "Ns"],
        ).sort_values("time_s").reset_index(drop=True)
        raw["cycle_reset"] = (raw["Ns"].diff().fillna(0) < 0) | (raw["time_s"].diff().fillna(0) < 0)
        raw["cycle_id"] = raw["cycle_reset"].cumsum().astype(int)

        cyc = (
            raw.groupby("cycle_id")
            .agg(
                raw_cycle_number=("cycleNumber", "first"),
                time_start_s=("time_s", "min"),
                time_end_s=("time_s", "max"),
                current_abs_mean_a=("I_mA", lambda s: float(np.abs(s).mean() / 1000.0)),
                p95_abs_current_a=("I_mA", lambda s: float(np.percentile(np.abs(s), 95) / 1000.0)),
                current_span_a=("I_mA", lambda s: float((np.abs(s).max() - np.abs(s).min()) / 1000.0)),
                temp_mean_c=("Temperature__C", "mean"),
                temp_max_c=("Temperature__C", "max"),
                temp_min_c=("Temperature__C", "min"),
                q_charge_mah=("QCharge_mA_h", "max"),
                q_discharge_mah=("QDischarge_mA_h", "max"),
                ns_count=("Ns", "nunique"),
            )
            .reset_index()
            .sort_values("time_start_s")
            .reset_index(drop=True)
        )
        cyc["cycle_index"] = np.arange(len(cyc))
        cyc["countable_discharge_cycle"] = cyc["ns_count"].between(7, 8)
        cyc["mission_cycle_index"] = cyc["countable_discharge_cycle"].cumsum().astype(int)
        cyc["mission_discharge_index"] = cyc["mission_cycle_index"].shift(fill_value=0).astype(int)

        cap = cyc.loc[cyc["ns_count"] >= CAPACITY_TEST_NS_THRESHOLD].copy()
        if len(cap) < 2:
            continue

        base_capacity_mah = float(cap["q_discharge_mah"].iloc[: min(3, len(cap))].max())
        cyc["file_id"] = path.stem
        cyc["protocol"] = EVTOL_PROTOCOLS.get(path.stem, "Unknown")
        cyc["base_capacity_mah"] = base_capacity_mah
        cyc["event_duration_s"] = cyc["time_end_s"] - cyc["time_start_s"]
        cyc["duration_h"] = cyc["event_duration_s"] / 3600.0
        cyc["q_discharge_frac"] = cyc["q_discharge_mah"] / base_capacity_mah
        cyc["cumulative_equiv_cycles"] = cyc["q_discharge_frac"].cumsum()
        cyc["event_efc"] = cyc["q_discharge_frac"]
        cyc["event_ah"] = cyc["q_discharge_mah"] / 1000.0
        cyc["cumulative_efc"] = cyc["event_efc"].cumsum()
        cyc["cumulative_ah"] = cyc["event_ah"].cumsum()
        cyc["temp_span_c"] = cyc["temp_max_c"] - cyc["temp_min_c"]

        cap = cyc.loc[cyc["ns_count"] >= CAPACITY_TEST_NS_THRESHOLD].copy().reset_index(drop=True)
        cap["anchor_order"] = np.arange(len(cap))
        cap["mission_discharge_index"] = cap["mission_cycle_index"].shift(fill_value=0).astype(int)
        cap["discharge_events_since_prior_capacity_test"] = cap["mission_discharge_index"].diff().fillna(0).astype(int)
        cap["anchor_soh_pct"] = 100.0 * cap["q_discharge_mah"] / base_capacity_mah
        anchor_frames.append(
            cap[
                [
                    "file_id",
                    "protocol",
                    "cycle_id",
                    "cycle_index",
                    "raw_cycle_number",
                    "mission_cycle_index",
                    "anchor_order",
                    "mission_discharge_index",
                    "discharge_events_since_prior_capacity_test",
                    "time_start_s",
                    "time_end_s",
                    "q_discharge_mah",
                    "base_capacity_mah",
                    "anchor_soh_pct",
                    "cumulative_equiv_cycles",
                ]
            ]
        )

        cap_positions = cap["cycle_index"].to_list()
        for start_cycle_index, end_cycle_index in zip(cap_positions[:-1], cap_positions[1:]):
            current = cyc.loc[cyc["cycle_index"].eq(start_cycle_index)].iloc[0]
            nxt = cyc.loc[cyc["cycle_index"].eq(end_cycle_index)].iloc[0]
            mission = cyc.loc[(cyc["cycle_index"] > start_cycle_index) & (cyc["cycle_index"] < end_cycle_index)].copy()
            if mission.empty:
                continue

            interval_rows.append(
                {
                    "file_id": path.stem,
                    "protocol": EVTOL_PROTOCOLS.get(path.stem, "Unknown"),
                    "current_soh_pct": 100.0 * current["q_discharge_mah"] / base_capacity_mah,
                    "latent_soh_filter_pct": 100.0 * current["q_discharge_mah"] / base_capacity_mah,
                    "target_next_soh_pct": 100.0 * nxt["q_discharge_mah"] / base_capacity_mah,
                    "target_delta_soh_pct": 100.0 * (nxt["q_discharge_mah"] - current["q_discharge_mah"]) / base_capacity_mah,
                    "duration_h": mission["duration_h"].sum(),
                    "dod_frac": mission["q_discharge_mah"].sum() / base_capacity_mah,
                    "temp_mean_c": mission["temp_mean_c"].mean(),
                    "temp_max_c": mission["temp_max_c"].max(),
                    "temp_span_c": mission["temp_max_c"].max() - mission["temp_min_c"].min(),
                    "cumulative_equiv_cycles": float(current["cumulative_equiv_cycles"]),
                    "gap_h": (nxt["time_start_s"] - current["time_end_s"]) / 3600.0,
                    "current_abs_mean_a": mission["current_abs_mean_a"].mean(),
                    "p95_abs_current_a": mission["p95_abs_current_a"].max(),
                    "current_span_a": mission["current_span_a"].max(),
                    "avg_cell_temp_mean_c": mission["temp_mean_c"].mean(),
                    "avg_cell_temp_max_c": mission["temp_max_c"].max(),
                    "avg_cell_temp_span_c": mission["temp_span_c"].mean(),
                    "soc_span_pct": 100.0 * mission["q_discharge_mah"].sum() / base_capacity_mah,
                    "event_duration_s": mission["event_duration_s"].sum(),
                    "delta_days": (nxt["time_start_s"] - current["time_end_s"]) / 86400.0,
                    "event_efc": mission["q_discharge_mah"].sum() / base_capacity_mah,
                    "event_ah": mission["q_discharge_mah"].sum() / 1000.0,
                    "cumulative_efc": float(current["cumulative_efc"]),
                    "cumulative_ah": float(current["cumulative_ah"]),
                    "cumulative_flight_count": int(current["mission_discharge_index"]),
                    "time_since_prev_event_days": (nxt["time_start_s"] - current["time_end_s"]) / 86400.0,
                    "capacity_test_start_cycle_id": int(current["cycle_id"]),
                    "capacity_test_end_cycle_id": int(nxt["cycle_id"]),
                    "capacity_test_start_cycle_index": int(current["cycle_index"]),
                    "capacity_test_end_cycle_index": int(nxt["cycle_index"]),
                    "interval_cycle_count": int(len(mission)),
                }
            )

    interval_df = pd.DataFrame(interval_rows)
    anchor_df = pd.concat(anchor_frames, ignore_index=True)
    anchor_df["adjusted_health_pct"] = 100.0 * (anchor_df["anchor_soh_pct"] - 80.0) / 20.0
    anchor_df["adjusted_health_clipped_pct"] = anchor_df["adjusted_health_pct"].clip(lower=0.0, upper=100.0)
    interval_df[SHARED_FEATURES] = interval_df[SHARED_FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return interval_df, anchor_df


def build_plane_flight_dataset(latent_path: Path) -> pd.DataFrame:
    raw = pd.read_csv(latent_path, parse_dates=["event_datetime"])
    raw = raw.loc[raw["event_type"].eq("flight")].copy()
    raw = raw.sort_values(["battery_id", "event_datetime"]).reset_index(drop=True)

    parts: list[pd.DataFrame] = []
    for battery_id, g in raw.groupby("battery_id"):
        g = g.copy().sort_values("event_datetime").reset_index(drop=True)
        g["flight_index"] = np.arange(len(g))
        g["latent_soh_filter_pct"] = _num(g["latent_soh_filter_pct"], default=np.nan)
        g["current_soh_pct"] = g["latent_soh_filter_pct"]
        g["target_next_soh_pct"] = g["current_soh_pct"].shift(-1)
        g["target_delta_soh_pct"] = g["target_next_soh_pct"] - g["current_soh_pct"]
        g["event_duration_s"] = _num(g["event_duration_s"])
        g["duration_h"] = g["event_duration_s"] / 3600.0
        g["soc_span_pct"] = _num(g["soc_span_pct"])
        g["dod_frac"] = g["soc_span_pct"] / 100.0
        g["temp_mean_c"] = _num(g["avg_cell_temp_mean_c"])
        g["temp_max_c"] = _num(g["avg_cell_temp_max_c"])
        g["temp_span_c"] = _num(g["avg_cell_temp_span_c"])
        g["current_abs_mean_a"] = _num(g["current_abs_mean_a"])
        g["p95_abs_current_a"] = _num(g["p95_abs_current_a"])
        g["current_span_a"] = _num(g["current_span_a"])
        g["avg_cell_temp_mean_c"] = g["temp_mean_c"]
        g["avg_cell_temp_max_c"] = g["temp_max_c"]
        g["avg_cell_temp_span_c"] = g["temp_span_c"]
        g["gap_h"] = ((g["event_datetime"] - g["event_datetime"].shift(1)).dt.total_seconds() / 3600.0).fillna(0.0)
        g["delta_days"] = g["gap_h"] / 24.0
        g["time_since_prev_event_days"] = g["delta_days"]
        g["event_efc"] = _num(g["event_efc"]) if "event_efc" in g.columns else g["dod_frac"]
        g["event_ah"] = _num(g["event_ah"]) if "event_ah" in g.columns else (g["current_abs_mean_a"] * g["duration_h"]).abs()
        g["cumulative_efc"] = _num(g["cumulative_efc"]) if "cumulative_efc" in g.columns else g["event_efc"].cumsum()
        g["cumulative_ah"] = _num(g["cumulative_ah"]) if "cumulative_ah" in g.columns else g["event_ah"].cumsum()
        g["cumulative_flight_count"] = _num(g["cumulative_flight_count"]) if "cumulative_flight_count" in g.columns else g["flight_index"]
        g["cumulative_equiv_cycles"] = g["cumulative_efc"]
        parts.append(g)

    out = pd.concat(parts, ignore_index=True)
    out = out.dropna(subset=["current_soh_pct", "target_next_soh_pct", "target_delta_soh_pct"]).copy()
    out[SHARED_FEATURES] = out[SHARED_FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def assign_evtol_splits(evtol_df: pd.DataFrame) -> pd.DataFrame:
    out = evtol_df.copy()
    evtol_files = sorted(out["file_id"].unique())
    evtol_train_files = evtol_files[:15]
    evtol_val_files = evtol_files[15:18]
    out["split"] = np.where(
        out["file_id"].isin(evtol_train_files),
        "train",
        np.where(out["file_id"].isin(evtol_val_files), "val", "test"),
    )
    return out


def assign_plane_time_splits(plane_df: pd.DataFrame, train_frac: float = 0.70, val_frac: float = 0.15) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for _, g in plane_df.groupby("battery_id"):
        part = g.sort_values("event_datetime").copy()
        n = len(part)
        idx_train_end = max(1, int(round(n * train_frac)))
        idx_val_end = max(idx_train_end + 1, int(round(n * (train_frac + val_frac))))
        part["split"] = "train"
        part.iloc[idx_train_end:idx_val_end, part.columns.get_loc("split")] = "val"
        part.iloc[idx_val_end:, part.columns.get_loc("split")] = "test"
        parts.append(part)
    return pd.concat(parts, ignore_index=True)
