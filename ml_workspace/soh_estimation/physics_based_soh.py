from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

try:
    import yaml
except ImportError:  # pragma: no cover - notebook fallback
    yaml = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
BATTERY_SPECS_PATH = PROJECT_ROOT / "ml_workspace" / "battery_specs.yaml"
BATTERY_INFERENCE_DIR = PROJECT_ROOT / "ml_workspace" / "battery_inference" / "output"
LATENT_SOH_DIR = PROJECT_ROOT / "ml_workspace" / "latent_soh" / "output"


RAW_TELEMETRY_COLUMNS = [
    "time_ms",
    "pack_current",
    "pack_soc",
    "pack_temp_avg",
    " bat 1 current",
    " bat 1 soc",
    " bat 1 soh",
    " bat 1 avg cell temp",
    " bat 2 current",
    " bat 2 soc",
    " bat 2 soh",
    " bat 2 avg cell temp",
]


@dataclass(frozen=True)
class PlanePaths:
    plane_id: str
    charge_summary_csv: Path
    observed_event_csv: Path


def get_plane_paths(plane_id: str) -> PlanePaths:
    plane_id = str(plane_id)
    return PlanePaths(
        plane_id=plane_id,
        charge_summary_csv=BATTERY_INFERENCE_DIR / f"plane_{plane_id}" / "charge_event_capacity_summary.csv",
        observed_event_csv=LATENT_SOH_DIR / f"plane_{plane_id}" / "event_observation_table.csv",
    )


def _file_size_mb(path: Path) -> float:
    return round(path.stat().st_size / 1_000_000, 2)


def inspect_data_directory() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    files = sorted(DATA_DIR.glob("*.parquet"))
    file_summary = pd.DataFrame(
        {
            "file": [p.name for p in files],
            "size_mb": [_file_size_mb(p) for p in files],
            "rows": [pq.ParquetFile(p).metadata.num_rows for p in files],
            "columns": [pq.ParquetFile(p).metadata.num_columns for p in files],
        }
    )

    manifest = pd.read_parquet(DATA_DIR / "event_manifest_corrected.parquet")
    manifest["plane_id"] = manifest["plane_id"].astype(str)
    manifest_summary = (
        manifest.groupby(["plane_id", "event_type_main_corrected"], dropna=False)
        .size()
        .rename("events")
        .reset_index()
        .sort_values(["plane_id", "events"], ascending=[True, False])
        .reset_index(drop=True)
    )

    telemetry_schema = pq.ParquetFile(DATA_DIR / "event_timeseries_corrected.parquet").read_row_group(0).column_names
    telemetry_summary = pd.DataFrame(
        {
            "selected_column": RAW_TELEMETRY_COLUMNS,
            "available": [col in telemetry_schema for col in RAW_TELEMETRY_COLUMNS],
            "why_it_matters": [
                "Per-row time base for coulomb counting.",
                "Pack-level charge/discharge current.",
                "Pack SOC trajectory.",
                "Pack thermal exposure during events.",
                "Battery 1 current for per-pack capacity estimates.",
                "Battery 1 SOC window selection.",
                "Battery 1 observed BMS SOH points.",
                "Battery 1 thermal exposure.",
                "Battery 2 current for per-pack capacity estimates.",
                "Battery 2 SOC window selection.",
                "Battery 2 observed BMS SOH points.",
                "Battery 2 thermal exposure.",
            ],
        }
    )
    return file_summary, manifest_summary, telemetry_summary


def load_rated_capacity_ah(plane_id: str, default_capacity_ah: float = 29.4) -> float:
    if yaml is None or not BATTERY_SPECS_PATH.exists():
        return default_capacity_ah
    with BATTERY_SPECS_PATH.open("r", encoding="utf-8") as handle:
        specs = yaml.safe_load(handle)
    plane_spec = (specs or {}).get("planes", {}).get(str(plane_id), {})
    return float(
        plane_spec.get("rated_capacity", {})
        .get("c50_discharge_20a", {})
        .get("capacity_ah", default_capacity_ah)
    )


def _validate_paths(paths: PlanePaths) -> None:
    missing = [path for path in [paths.charge_summary_csv, paths.observed_event_csv] if not path.exists()]
    if missing:
        missing_str = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Missing required SOH inputs for plane {paths.plane_id}: {missing_str}")


def load_charge_physics_dataset(
    plane_id: str = "166",
    reference_events: int = 10,
    min_soc_span_pct: float = 20.0,
) -> pd.DataFrame:
    paths = get_plane_paths(plane_id)
    _validate_paths(paths)

    rated_capacity_ah = load_rated_capacity_ah(plane_id)
    charge = pd.read_csv(paths.charge_summary_csv, parse_dates=["event_datetime"])
    observed = pd.read_csv(paths.observed_event_csv, parse_dates=["event_datetime"])

    observed_charge = observed.loc[observed["event_type"] == "charge", ["battery_id", "flight_id", "event_datetime", "observed_soh_pct"]]
    merged = (
        charge.merge(observed_charge, on=["battery_id", "flight_id", "event_datetime"], how="inner")
        .sort_values(["battery_id", "event_datetime", "flight_id"])
        .reset_index(drop=True)
    )
    merged = merged.loc[merged["soc_span"] >= min_soc_span_pct].copy()
    merged["plane_id"] = str(plane_id)
    merged["rated_capacity_ah"] = rated_capacity_ah
    merged["physics_soh_absolute_pct"] = 100.0 * merged["capacity_est_ah"] / rated_capacity_ah

    reference_capacity = (
        merged.groupby("battery_id")["capacity_est_ah"]
        .apply(lambda series: series.head(reference_events).median())
        .rename("reference_capacity_ah")
        .reset_index()
    )
    merged = merged.merge(reference_capacity, on="battery_id", how="left")
    merged["physics_soh_relative_pct"] = 100.0 * merged["capacity_est_ah"] / merged["reference_capacity_ah"]
    merged["days_from_start"] = (
        merged["event_datetime"] - merged.groupby("battery_id")["event_datetime"].transform("min")
    ).dt.total_seconds() / 86400.0
    return merged


def score_models(
    frame: pd.DataFrame,
    model_columns: Iterable[str] = ("physics_soh_absolute_pct", "physics_soh_relative_pct"),
) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    clean = frame.dropna(subset=["observed_soh_pct"]).copy()
    for model_column in model_columns:
        scored = clean.dropna(subset=[model_column])
        if scored.empty:
            continue
        for scope, scope_frame in [("overall", scored), *[(f"battery_{battery_id}", battery_frame) for battery_id, battery_frame in scored.groupby("battery_id")]]:
            rows.append(
                {
                    "model": model_column,
                    "scope": scope,
                    "n": int(len(scope_frame)),
                    "mae": mean_absolute_error(scope_frame["observed_soh_pct"], scope_frame[model_column]),
                    "rmse": mean_squared_error(scope_frame["observed_soh_pct"], scope_frame[model_column]) ** 0.5,
                    "r2": r2_score(scope_frame["observed_soh_pct"], scope_frame[model_column]),
                }
            )
    return pd.DataFrame(rows).sort_values(["model", "scope"]).reset_index(drop=True)
