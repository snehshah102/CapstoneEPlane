from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq


def _normalize_schema(schema: pa.Schema) -> pa.Schema:
    fields = []
    for field in schema:
        if pa.types.is_null(field.type):
            fields.append(pa.field(field.name, pa.string(), nullable=True, metadata=field.metadata))
        else:
            fields.append(field)
    return pa.schema(fields, metadata=schema.metadata)


def build_event_direction_corrections(
    timeseries_path: str | Path,
    manifest_path: str | Path,
    soc_threshold_pct: float = 2.0,
    start_end_window_rows: int = 20,
    min_rows_per_pack_event: int = 5,
) -> pd.DataFrame:
    dataset = ds.dataset(str(timeseries_path), format="parquet")
    columns = [
        "plane_id",
        "flight_id",
        "event_datetime",
        "is_charging_event",
        "is_flight_event",
        "source_csv_kind",
        "source_pack_id",
        "time_ms",
        " bat 1 soc",
        " bat 2 soc",
    ]
    table = dataset.to_table(
        columns=columns,
        filter=(ds.field("source_csv_kind") == "aux") & ((ds.field("source_pack_id") == 1) | (ds.field("source_pack_id") == 2)),
    )
    raw_df = table.to_pandas()
    raw_df["event_datetime"] = pd.to_datetime(raw_df["event_datetime"], errors="coerce")

    pack_rows: list[dict[str, object]] = []
    for battery_id in (1, 2):
        soc_col = f" bat {battery_id} soc"
        sub = raw_df.loc[raw_df["source_pack_id"] == battery_id].copy()
        sub["soc_pct"] = pd.to_numeric(sub[soc_col], errors="coerce")
        sub["time_ms"] = pd.to_numeric(sub["time_ms"], errors="coerce")
        sub = sub.dropna(subset=["soc_pct", "time_ms", "event_datetime"])

        group_cols = ["plane_id", "flight_id", "event_datetime", "is_charging_event", "is_flight_event"]
        for keys, group in sub.groupby(group_cols, sort=False):
            g = group.sort_values("time_ms").drop_duplicates("time_ms")
            if len(g) < min_rows_per_pack_event:
                continue
            window = min(start_end_window_rows, len(g))
            soc_start = g["soc_pct"].head(window).median()
            soc_end = g["soc_pct"].tail(window).median()
            pack_rows.append(
                {
                    "plane_id": str(keys[0]),
                    "flight_id": int(keys[1]),
                    "event_datetime": keys[2],
                    "is_charging_event_original": int(keys[3]),
                    "is_flight_event_original": int(keys[4]),
                    "battery_id": battery_id,
                    "soc_start": float(soc_start),
                    "soc_end": float(soc_end),
                    "delta_soc": float(soc_end - soc_start),
                    "n_rows": int(len(g)),
                }
            )

    pack_df = pd.DataFrame(pack_rows)
    pack_df["pack_direction"] = np.where(
        pack_df["delta_soc"] >= float(soc_threshold_pct),
        "charge",
        np.where(pack_df["delta_soc"] <= -float(soc_threshold_pct), "discharge", "flat"),
    )

    event_rows: list[dict[str, object]] = []
    group_cols = ["plane_id", "flight_id", "event_datetime", "is_charging_event_original", "is_flight_event_original"]
    for keys, group in pack_df.groupby(group_cols, sort=False):
        directions = group["pack_direction"].tolist()
        if all(direction == "charge" for direction in directions):
            inferred = "charge"
        elif all(direction == "discharge" for direction in directions):
            inferred = "discharge"
        elif any(direction == "charge" for direction in directions) and any(direction == "discharge" for direction in directions):
            inferred = "mixed"
        elif any(direction == "charge" for direction in directions):
            inferred = "charge_weak"
        elif any(direction == "discharge" for direction in directions):
            inferred = "discharge_weak"
        else:
            inferred = "flat"

        event_rows.append(
            {
                "plane_id": str(keys[0]),
                "flight_id": int(keys[1]),
                "event_datetime": keys[2],
                "is_charging_event_original": int(keys[3]),
                "is_flight_event_original": int(keys[4]),
                "inferred_event_direction": inferred,
                "pack_directions": "/".join(
                    f"{int(battery_id)}:{direction}" for battery_id, direction in zip(group["battery_id"], group["pack_direction"])
                ),
                "delta_soc_mean": float(group["delta_soc"].mean()),
                "delta_soc_min": float(group["delta_soc"].min()),
                "delta_soc_max": float(group["delta_soc"].max()),
                "soc_start_mean": float(group["soc_start"].mean()),
                "soc_end_mean": float(group["soc_end"].mean()),
                "pack_event_count": int(len(group)),
            }
        )

    event_df = pd.DataFrame(event_rows)
    manifest = pd.read_parquet(
        manifest_path,
        columns=[
            "plane_id",
            "flight_id",
            "event_datetime",
            "event_type_main",
            "is_charging_event",
            "is_flight_event",
            "is_ground_test_event",
        ],
    )
    manifest["plane_id"] = manifest["plane_id"].astype(str)
    manifest["event_datetime"] = pd.to_datetime(manifest["event_datetime"], errors="coerce")
    event_df = event_df.merge(
        manifest.rename(
            columns={
                "event_type_main": "event_type_main_original",
                "is_charging_event": "_manifest_is_charging_event",
                "is_flight_event": "_manifest_is_flight_event",
                "is_ground_test_event": "is_ground_test_event_original",
            }
        ),
        on=["plane_id", "flight_id", "event_datetime"],
        how="left",
    )

    event_df["event_type_main_original"] = event_df["event_type_main_original"].fillna("unknown")
    event_df["is_ground_test_event_original"] = event_df["is_ground_test_event_original"].fillna(0).astype(int)

    corrected_charge = event_df["is_charging_event_original"].copy()
    corrected_flight = event_df["is_flight_event_original"].copy()
    corrected_type = event_df["event_type_main_original"].copy()
    correction_reason = pd.Series("ambiguous_preserved", index=event_df.index, dtype="object")

    charge_like = event_df["inferred_event_direction"].isin(["charge", "charge_weak"])
    discharge_like = event_df["inferred_event_direction"].isin(["discharge", "discharge_weak"])
    preserve_ground_test = discharge_like & (event_df["is_ground_test_event_original"] == 1) & (
        event_df["event_type_main_original"] == "ground_test"
    )

    corrected_charge.loc[charge_like] = 1
    corrected_flight.loc[charge_like] = 0
    corrected_type.loc[charge_like] = "charging"
    correction_reason.loc[charge_like] = "soc_inferred_charge"

    corrected_charge.loc[discharge_like] = 0
    corrected_flight.loc[discharge_like] = 1
    corrected_type.loc[discharge_like] = "flight"
    correction_reason.loc[discharge_like] = "soc_inferred_discharge"

    corrected_flight.loc[preserve_ground_test] = 0
    corrected_type.loc[preserve_ground_test] = "ground_test"
    correction_reason.loc[preserve_ground_test] = "soc_inferred_discharge_preserve_ground_test"

    event_df["is_charging_event_corrected"] = corrected_charge.astype(int)
    event_df["is_flight_event_corrected"] = corrected_flight.astype(int)
    event_df["event_type_main_corrected"] = corrected_type.astype("object")
    event_df["correction_reason"] = correction_reason
    event_df["correction_applied"] = (
        (event_df["is_charging_event_corrected"] != event_df["is_charging_event_original"])
        | (event_df["is_flight_event_corrected"] != event_df["is_flight_event_original"])
        | (event_df["event_type_main_corrected"] != event_df["event_type_main_original"])
    ).astype(int)
    event_df["direction_soc_threshold_pct"] = float(soc_threshold_pct)
    return event_df.sort_values(["plane_id", "event_datetime", "flight_id"]).reset_index(drop=True)


def write_corrected_manifest(
    manifest_path: str | Path,
    corrections_df: pd.DataFrame,
    output_path: str | Path,
) -> dict[str, int]:
    manifest = pd.read_parquet(manifest_path)
    manifest["plane_id"] = manifest["plane_id"].astype(str)
    manifest["event_datetime"] = pd.to_datetime(manifest["event_datetime"], errors="coerce")

    keep_cols = [
        "plane_id",
        "flight_id",
        "event_datetime",
        "event_type_main_original",
        "is_charging_event_original",
        "is_flight_event_original",
        "inferred_event_direction",
        "pack_directions",
        "delta_soc_mean",
        "delta_soc_min",
        "delta_soc_max",
        "soc_start_mean",
        "soc_end_mean",
        "pack_event_count",
        "direction_soc_threshold_pct",
        "event_type_main_corrected",
        "is_charging_event_corrected",
        "is_flight_event_corrected",
        "correction_reason",
        "correction_applied",
    ]
    merged = manifest.merge(corrections_df[keep_cols], on=["plane_id", "flight_id", "event_datetime"], how="left")

    merged["event_type_main_original"] = merged["event_type_main_original"].fillna(merged["event_type_main"])
    merged["is_charging_event_original"] = merged["is_charging_event_original"].fillna(merged["is_charging_event"]).astype(int)
    merged["is_flight_event_original"] = merged["is_flight_event_original"].fillna(merged["is_flight_event"]).astype(int)
    merged["event_type_main_corrected"] = merged["event_type_main_corrected"].fillna(merged["event_type_main"])
    merged["is_charging_event_corrected"] = merged["is_charging_event_corrected"].fillna(merged["is_charging_event"]).astype(int)
    merged["is_flight_event_corrected"] = merged["is_flight_event_corrected"].fillna(merged["is_flight_event"]).astype(int)
    merged["correction_reason"] = merged["correction_reason"].fillna("no_aux_direction")
    merged["correction_applied"] = merged["correction_applied"].fillna(0).astype(int)

    merged["event_type_main"] = merged["event_type_main_corrected"]
    merged["is_charging_event"] = merged["is_charging_event_corrected"]
    merged["is_flight_event"] = merged["is_flight_event_corrected"]
    merged.to_parquet(output_path, index=False)
    return {
        "rows": int(len(merged)),
        "corrected_events": int(merged["correction_applied"].sum()),
    }


def write_corrected_timeseries(
    timeseries_path: str | Path,
    corrections_df: pd.DataFrame,
    output_path: str | Path,
    batch_size: int = 25_000,
) -> dict[str, int]:
    join_cols = [
        "plane_id",
        "flight_id",
        "event_datetime",
    ]
    correction_cols = join_cols + [
        "event_type_main_original",
        "is_charging_event_original",
        "is_flight_event_original",
        "inferred_event_direction",
        "direction_soc_threshold_pct",
        "event_type_main_corrected",
        "is_charging_event_corrected",
        "is_flight_event_corrected",
        "correction_reason",
        "correction_applied",
    ]
    correction_map = corrections_df[correction_cols].copy()
    correction_map["plane_id"] = correction_map["plane_id"].astype(str)
    correction_map["event_datetime"] = pd.to_datetime(correction_map["event_datetime"], errors="coerce")

    dataset = ds.dataset(str(timeseries_path), format="parquet")
    writer: pq.ParquetWriter | None = None
    target_schema: pa.Schema | None = None
    rows_written = 0
    output_path = Path(output_path)
    if output_path.exists():
        output_path.unlink()

    try:
        for batch in dataset.to_batches(batch_size=int(batch_size)):
            batch_df = batch.to_pandas()
            batch_df["plane_id"] = batch_df["plane_id"].astype(str)
            batch_df["event_datetime"] = pd.to_datetime(batch_df["event_datetime"], errors="coerce")

            merged = batch_df.merge(correction_map, on=["plane_id", "flight_id", "event_datetime"], how="left")
            merged["event_type_main_original"] = merged["event_type_main_original"].fillna(merged["event_type_main"])
            merged["is_charging_event_original"] = merged["is_charging_event_original"].fillna(merged["is_charging_event"]).astype(int)
            merged["is_flight_event_original"] = merged["is_flight_event_original"].fillna(merged["is_flight_event"]).astype(int)
            merged["event_type_main_corrected"] = merged["event_type_main_corrected"].fillna(merged["event_type_main"])
            merged["is_charging_event_corrected"] = merged["is_charging_event_corrected"].fillna(merged["is_charging_event"]).astype(int)
            merged["is_flight_event_corrected"] = merged["is_flight_event_corrected"].fillna(merged["is_flight_event"]).astype(int)
            merged["correction_reason"] = merged["correction_reason"].fillna("no_aux_direction")
            merged["correction_applied"] = merged["correction_applied"].fillna(0).astype(int)

            merged["event_type_main"] = merged["event_type_main_corrected"]
            merged["is_charging_event"] = merged["is_charging_event_corrected"]
            merged["is_flight_event"] = merged["is_flight_event_corrected"]

            table = pa.Table.from_pandas(merged, preserve_index=False)
            if writer is None:
                target_schema = _normalize_schema(table.schema)
                table = table.cast(target_schema, safe=False)
                writer = pq.ParquetWriter(str(output_path), target_schema, compression="zstd")
            elif target_schema is not None:
                table = table.cast(target_schema, safe=False)
            writer.write_table(table)
            rows_written += len(merged)
    finally:
        if writer is not None:
            writer.close()

    return {
        "rows": int(rows_written),
    }


def create_corrected_event_parquets(
    timeseries_path: str | Path,
    manifest_path: str | Path,
    output_dir: str | Path,
    soc_threshold_pct: float = 2.0,
    start_end_window_rows: int = 20,
    min_rows_per_pack_event: int = 5,
    batch_size: int = 25_000,
) -> dict[str, object]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    corrections_df = build_event_direction_corrections(
        timeseries_path=timeseries_path,
        manifest_path=manifest_path,
        soc_threshold_pct=soc_threshold_pct,
        start_end_window_rows=start_end_window_rows,
        min_rows_per_pack_event=min_rows_per_pack_event,
    )
    corrections_path = output_dir / "event_direction_corrections.csv"
    corrections_df.to_csv(corrections_path, index=False)

    manifest_out = output_dir / "event_manifest_corrected.parquet"
    timeseries_out = output_dir / "event_timeseries_corrected.parquet"
    manifest_stats = write_corrected_manifest(manifest_path, corrections_df, manifest_out)
    timeseries_stats = write_corrected_timeseries(
        timeseries_path,
        corrections_df,
        timeseries_out,
        batch_size=batch_size,
    )

    summary = {
        "soc_threshold_pct": float(soc_threshold_pct),
        "start_end_window_rows": int(start_end_window_rows),
        "min_rows_per_pack_event": int(min_rows_per_pack_event),
        "audited_events": int(len(corrections_df)),
        "corrected_events": int(corrections_df["correction_applied"].sum()),
        "correction_reason_counts": corrections_df["correction_reason"].value_counts().to_dict(),
        "inferred_direction_counts": corrections_df["inferred_event_direction"].value_counts().to_dict(),
        "manifest_rows": manifest_stats["rows"],
        "timeseries_rows": timeseries_stats["rows"],
        "output_manifest_path": str(manifest_out),
        "output_timeseries_path": str(timeseries_out),
        "corrections_csv_path": str(corrections_path),
    }
    (output_dir / "correction_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create corrected event parquet files using SOC-direction audit logic")
    parser.add_argument("--timeseries-path", default="data/event_timeseries.parquet")
    parser.add_argument("--manifest-path", default="data/event_manifest.parquet")
    parser.add_argument("--output-dir", default="data_corrected")
    parser.add_argument("--soc-threshold-pct", type=float, default=2.0)
    parser.add_argument("--start-end-window-rows", type=int, default=20)
    parser.add_argument("--min-rows-per-pack-event", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=25_000)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = create_corrected_event_parquets(
        timeseries_path=args.timeseries_path,
        manifest_path=args.manifest_path,
        output_dir=args.output_dir,
        soc_threshold_pct=args.soc_threshold_pct,
        start_end_window_rows=args.start_end_window_rows,
        min_rows_per_pack_event=args.min_rows_per_pack_event,
        batch_size=args.batch_size,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
