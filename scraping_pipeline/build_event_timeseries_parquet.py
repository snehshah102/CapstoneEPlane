#!/usr/bin/env python3
"""Build processed parquet datasets from scraped Pipistrel event folders.

Outputs:
- data/processed/event_manifest.parquet: one row per event metadata file
- data/processed/event_timeseries.parquet: concatenated raw CSV rows with event metadata

The timeseries parquet preserves original raw CSV columns and adds normalized metadata
columns so charge-vs-flight analysis is easy without losing fidelity.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pandas.errors import ParserError

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_RAW_ROOT = PROJECT_ROOT / "data" / "raw_csv" / "by_plane"
DEFAULT_MANIFEST_OUT = PROJECT_ROOT / "data" / "processed" / "event_manifest.parquet"
DEFAULT_TIMESERIES_OUT = PROJECT_ROOT / "data" / "processed" / "event_timeseries.parquet"
DEFAULT_CHUNK_ROWS = 25000

CELL_SOH_COL_RE = re.compile(r"(?i)^\s*B\d+\s+SOH\s+CELL\s+\d+\s*$")
CELL_FSK_COL_RE = re.compile(r"(?i)^\s*B\d+\s+FSK\s+\d+\s*$")
CELL_KFL_COL_RE = re.compile(r"(?i)^\s*B\d+\s+KFL\s+\d+\s*$")
PACK_SOH_COL_RE = re.compile(r"(?i)^\s*bat\s+[12]\s+soh\s*$")
CSV_KIND_AUX_RE = re.compile(r"_(\d+)\.csv$", re.IGNORECASE)

FLOAT_CANONICAL_COLUMNS = [
    "time_ms",
    "time_min",
    "motor_power",
    "remaining_flight_time",
    "oat",
    "bat_1_current",
    "bat_1_voltage",
    "bat_1_soc",
    "bat_1_temp_min",
    "bat_1_temp_max",
    "bat_1_temp_avg",
    "bat_1_cell_v_min",
    "bat_1_cell_v_max",
    "bat_2_current",
    "bat_2_voltage",
    "bat_2_soc",
    "bat_2_temp_min",
    "bat_2_temp_max",
    "bat_2_temp_avg",
    "bat_2_cell_v_min",
    "bat_2_cell_v_max",
    "pack_current",
    "pack_voltage",
    "pack_soc",
    "pack_temp_min",
    "pack_temp_max",
    "pack_temp_avg",
    "pack_cell_v_min",
    "pack_cell_v_max",
]
INT_CANONICAL_COLUMNS = ["source_pack_id"]
CANONICAL_COLUMNS = FLOAT_CANONICAL_COLUMNS + INT_CANONICAL_COLUMNS

STRING_META_COLUMNS = [
    "plane_id",
    "registration",
    "event_dir_name",
    "event_dir_path",
    "detail_date",
    "detail_flight_type",
    "detail_duration",
    "detail_note",
    "route",
    "pilot",
    "aircraft_type",
    "detail_aircraft",
    "fleet",
    "departure_airport",
    "destination_airport",
    "battery_type",
    "end_of_flight_hobbs",
    "csv_files",
    "csv_zip_url",
    "csv_zip_path",
    "csv_zip_sha256",
    "note_txt_path",
    "metadata_path",
    "scraped_at_utc",
    "scrape_error",
    "event_type_main",
    "source_csv_name",
    "source_csv_path",
    "source_csv_kind",
]
INT_META_COLUMNS = [
    "flight_id",
    "csv_found",
    "csv_file_count",
    "is_charging_event",
    "is_flight_event",
    "is_ground_test_event",
]
DATETIME_META_COLUMNS = ["event_datetime", "event_date"]
META_COLUMNS = STRING_META_COLUMNS + INT_META_COLUMNS + DATETIME_META_COLUMNS


RAW_INT = "integer"
RAW_FLOAT = "float"
RAW_STRING = "string"


class SimpleProgressBar:
    def __init__(self, total: int, label: str, enabled: bool = True) -> None:
        self.total = max(int(total), 0)
        self.label = label
        self.enabled = enabled and self.total > 0
        self.current = 0
        self.width = 28
        if self.enabled:
            self._render("starting")

    def update(self, step: int = 1, detail: str = "") -> None:
        if not self.enabled:
            return
        self.current = min(self.total, self.current + step)
        self._render(detail)

    def close(self) -> None:
        if not self.enabled:
            return
        self._render("done")
        sys.stderr.write("\n")
        sys.stderr.flush()

    def _render(self, detail: str) -> None:
        ratio = self.current / self.total if self.total else 1.0
        filled = int(self.width * ratio)
        bar = "#" * filled + "-" * (self.width - filled)
        detail_text = f" | {detail}" if detail else ""
        sys.stderr.write(
            f"\r{self.label}: [{bar}] {self.current}/{self.total} ({ratio * 100:5.1f}%)" + detail_text
        )
        sys.stderr.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build parquet datasets from raw event CSV folders.")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT), help="Root folder containing plane event folders.")
    parser.add_argument("--manifest-out", default=str(DEFAULT_MANIFEST_OUT), help="Output parquet for event manifest.")
    parser.add_argument("--timeseries-out", default=str(DEFAULT_TIMESERIES_OUT), help="Output parquet for concatenated event timeseries.")
    parser.add_argument("--include-warns", action="store_true", help="Include *_warns.csv files in the timeseries parquet.")
    parser.add_argument("--include-soh-columns", action="store_true", help="Keep all raw SOH columns, including per-cell SOH columns.")
    parser.add_argument("--max-events", type=int, default=0, help="Optional cap for smoke runs. 0 means all events.")
    parser.add_argument("--chunk-rows", type=int, default=DEFAULT_CHUNK_ROWS, help="CSV rows per chunk when streaming into parquet.")
    parser.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True, help="Show a progress bar during long parquet builds.")
    return parser.parse_args()


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def parse_event_datetime(raw_value: str) -> pd.Timestamp:
    text = normalize_text(raw_value)
    if not text:
        return pd.NaT
    text = text.replace("a.m.", "AM").replace("p.m.", "PM")
    text = text.replace("a.m", "AM").replace("p.m", "PM")
    text = re.sub(r"\bSept\b", "Sep", text)
    text = re.sub(r"\b([A-Za-z]{3,9})\.", r"\1", text)
    text = re.sub(r",\s*noon$", ", 12:00 PM", text, flags=re.IGNORECASE)
    text = re.sub(r",\s*midnight$", ", 12:00 AM", text, flags=re.IGNORECASE)
    text = re.sub(r",\s*(\d{1,2})\s*(AM|PM)$", r", \1:00 \2", text, flags=re.IGNORECASE)
    for fmt in ("%b %d, %Y, %I:%M %p", "%B %d, %Y, %I:%M %p"):
        try:
            return pd.Timestamp(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return pd.NaT


def classify_event_type(raw_value: str) -> Dict[str, Any]:
    text = normalize_text(raw_value).lower()
    is_charging = int("charging" in text)
    is_flight = int("flight" in text)
    is_ground = int("ground test" in text)

    if is_charging and not is_flight and not is_ground:
        main = "charging"
    elif is_flight and not is_charging and not is_ground:
        main = "flight"
    elif is_ground and not is_charging and not is_flight:
        main = "ground_test"
    elif is_charging or is_flight or is_ground:
        main = "mixed"
    else:
        main = "unknown"

    return {
        "event_type_main": main,
        "is_charging_event": is_charging,
        "is_flight_event": is_flight,
        "is_ground_test_event": is_ground,
    }


def csv_kind_from_name(name: str) -> str:
    lower = name.lower()
    if lower.endswith("_warns.csv"):
        return "warns"
    if CSV_KIND_AUX_RE.search(lower):
        return "aux"
    return "raw"


def pack_id_from_name(name: str) -> int:
    match = CSV_KIND_AUX_RE.search(name)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def base_event_record(meta: Dict[str, Any], event_dir: Path) -> Dict[str, Any]:
    detail_date = normalize_text(meta.get("detail_date"))
    event_dt = parse_event_datetime(detail_date)
    event_type = classify_event_type(normalize_text(meta.get("detail_flight_type")))
    rec: Dict[str, Any] = {
        "flight_id": pd.to_numeric(meta.get("flight_id"), errors="coerce"),
        "plane_id": normalize_text(meta.get("aircraft_id")),
        "registration": normalize_text(meta.get("registration")),
        "event_dir_name": normalize_text(meta.get("event_dir_name")) or event_dir.name,
        "event_dir_path": str(event_dir.resolve()),
        "event_datetime": event_dt,
        "event_date": event_dt.normalize() if pd.notna(event_dt) else pd.NaT,
        "detail_date": detail_date,
        "detail_flight_type": normalize_text(meta.get("detail_flight_type")),
        "detail_duration": normalize_text(meta.get("detail_duration")),
        "detail_note": normalize_text(meta.get("detail_note")),
        "route": normalize_text(meta.get("route")),
        "pilot": normalize_text(meta.get("pilot")),
        "aircraft_type": normalize_text(meta.get("aircraft_type")),
        "detail_aircraft": normalize_text(meta.get("detail_aircraft")),
        "fleet": normalize_text(meta.get("fleet")),
        "departure_airport": normalize_text(meta.get("departure_airport")),
        "destination_airport": normalize_text(meta.get("destination_airport")),
        "battery_type": normalize_text(meta.get("battery_type")),
        "end_of_flight_hobbs": normalize_text(meta.get("end_of_flight_hobbs")),
        "csv_found": pd.to_numeric(meta.get("csv_found"), errors="coerce"),
        "csv_file_count": pd.to_numeric(meta.get("csv_file_count"), errors="coerce"),
        "csv_files": normalize_text(meta.get("csv_files")),
        "csv_zip_url": normalize_text(meta.get("csv_zip_url")),
        "csv_zip_path": normalize_text(meta.get("csv_zip_path")),
        "csv_zip_sha256": normalize_text(meta.get("csv_zip_sha256")),
        "note_txt_path": normalize_text(meta.get("note_txt_path")),
        "metadata_path": normalize_text(meta.get("metadata_path")),
        "scraped_at_utc": normalize_text(meta.get("scraped_at_utc")),
        "scrape_error": normalize_text(meta.get("scrape_error")),
    }
    rec.update(event_type)
    return rec


def iter_event_dirs(raw_root: Path) -> Iterable[Path]:
    for plane_dir in sorted(p for p in raw_root.iterdir() if p.is_dir()):
        for event_dir in sorted(p for p in plane_dir.iterdir() if p.is_dir()):
            if (event_dir / "event_metadata.json").exists():
                yield event_dir


def should_drop_column(column_name: Any, include_soh_columns: bool) -> bool:
    col = str(column_name).strip()
    if CELL_FSK_COL_RE.match(col) or CELL_KFL_COL_RE.match(col):
        return True
    if include_soh_columns:
        return False
    if CELL_SOH_COL_RE.match(col) and not PACK_SOH_COL_RE.match(col):
        return True
    return False


def list_event_csv_paths(event_dir: Path, include_warns: bool) -> list[Path]:
    csv_paths = sorted(p for p in event_dir.glob("*.csv") if p.is_file())
    selected: list[Path] = []
    for csv_path in csv_paths:
        if csv_kind_from_name(csv_path.name) == "warns" and not include_warns:
            continue
        selected.append(csv_path)
    return selected


def read_csv_header(csv_path: Path) -> list[str]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return next(reader)
        except StopIteration:
            return []


def collect_raw_columns(
    event_dirs: Sequence[Path],
    include_warns: bool,
    include_soh_columns: bool,
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for event_dir in event_dirs:
        for csv_path in list_event_csv_paths(event_dir, include_warns):
            for col in read_csv_header(csv_path):
                col_name = str(col)
                if should_drop_column(col_name, include_soh_columns):
                    continue
                if col_name not in seen:
                    seen.add(col_name)
                    ordered.append(col_name)
    return ordered


def collect_output_columns(raw_columns: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for col in list(raw_columns) + META_COLUMNS + CANONICAL_COLUMNS:
        if col not in seen:
            seen.add(col)
            ordered.append(col)
    return ordered


def iter_csv_chunks(csv_path: Path, chunk_rows: int, dtype: Any = None) -> Iterable[pd.DataFrame]:
    read_kwargs: Dict[str, Any] = {
        "chunksize": chunk_rows,
        "low_memory": False,
    }
    if dtype is not None:
        read_kwargs["dtype"] = dtype
        read_kwargs["keep_default_na"] = False
    try:
        yield from pd.read_csv(csv_path, **read_kwargs)
        return
    except (ParserError, MemoryError) as exc:
        if "out of memory" not in str(exc).lower():
            raise
    fallback_kwargs: Dict[str, Any] = {
        "chunksize": chunk_rows,
        "engine": "python",
        "on_bad_lines": "warn",
    }
    if dtype is not None:
        fallback_kwargs["dtype"] = dtype
        fallback_kwargs["keep_default_na"] = False
    yield from pd.read_csv(csv_path, **fallback_kwargs)


def infer_raw_column_types(
    event_dirs: Sequence[Path],
    raw_columns: Sequence[str],
    include_warns: bool,
    chunk_rows: int,
    show_progress: bool,
) -> Dict[str, str]:
    numeric_candidates = set(raw_columns)
    int_candidates = set(raw_columns)
    progress = SimpleProgressBar(len(event_dirs), "Inferring types", enabled=show_progress)

    try:
        for event_dir in event_dirs:
            for csv_path in list_event_csv_paths(event_dir, include_warns):
                for chunk in iter_csv_chunks(csv_path, chunk_rows, dtype=str):
                    for col in [name for name in chunk.columns if name in numeric_candidates]:
                        series = chunk[col].astype("string")
                        series = series.str.strip()
                        series = series[(series.notna()) & (series != "")]
                        if series.empty:
                            continue
                        numeric = pd.to_numeric(series, errors="coerce")
                        if numeric.isna().any():
                            numeric_candidates.discard(col)
                            int_candidates.discard(col)
                            continue
                        if col in int_candidates:
                            finite = numeric.dropna()
                            if not ((finite % 1) == 0).all():
                                int_candidates.discard(col)
            progress.update(detail=event_dir.name)
    finally:
        progress.close()

    inferred: Dict[str, str] = {}
    for col in raw_columns:
        if col in int_candidates:
            inferred[col] = RAW_INT
        elif col in numeric_candidates:
            inferred[col] = RAW_FLOAT
        else:
            inferred[col] = RAW_STRING
    return inferred


def to_nullable_int_series(value: Any, length: int) -> pd.Series:
    if pd.isna(value):
        return pd.Series(pd.array([pd.NA] * length, dtype="Int64"))
    return pd.Series(pd.array([int(value)] * length, dtype="Int64"))


def to_string_series(value: Any, length: int) -> pd.Series:
    text = normalize_text(value)
    if text == "":
        return pd.Series(pd.array([pd.NA] * length, dtype="string"))
    return pd.Series(pd.array([text] * length, dtype="string"))


def to_datetime_series(value: Any, length: int) -> pd.Series:
    if pd.isna(value):
        return pd.Series(pd.array([pd.NaT] * length, dtype="datetime64[ns]"))
    return pd.Series(pd.to_datetime([value] * length))


def build_meta_frame(meta_record: Dict[str, Any], csv_path: Path, length: int) -> pd.DataFrame:
    meta_cols = dict(meta_record)
    meta_cols["source_csv_name"] = csv_path.name
    meta_cols["source_csv_path"] = str(csv_path.resolve())
    meta_cols["source_csv_kind"] = csv_kind_from_name(csv_path.name)

    data: Dict[str, pd.Series] = {}
    for key in STRING_META_COLUMNS:
        data[key] = to_string_series(meta_cols.get(key), length)
    for key in INT_META_COLUMNS:
        data[key] = to_nullable_int_series(meta_cols.get(key), length)
    for key in DATETIME_META_COLUMNS:
        data[key] = to_datetime_series(meta_cols.get(key), length)
    return pd.DataFrame(data)


def as_float_series(series: pd.Series) -> pd.Series:
    clean = series.astype("string").str.strip()
    clean = clean.replace("", pd.NA)
    return pd.to_numeric(clean, errors="coerce").astype("float64")


def as_int_series(series: pd.Series) -> pd.Series:
    clean = series.astype("string").str.strip()
    clean = clean.replace("", pd.NA)
    return pd.to_numeric(clean, errors="coerce").astype("Int64")


def as_string_series(series: pd.Series) -> pd.Series:
    clean = series.astype("string")
    return clean.replace("", pd.NA)


def add_canonical_columns(df: pd.DataFrame, pack_id_hint: int) -> pd.DataFrame:
    out = df.copy()

    def copy_numeric(alias: str, source: str) -> None:
        if alias not in out.columns and source in out.columns:
            out[alias] = as_float_series(out[source])

    copy_numeric("time_ms", "time(ms)")
    copy_numeric("time_min", "time(min)")
    copy_numeric("motor_power", "motor power")
    copy_numeric("remaining_flight_time", "remaining flight time")
    if "oat" not in out.columns:
        if "OAT" in out.columns:
            out["oat"] = as_float_series(out["OAT"])
        elif "oat" in out.columns:
            out["oat"] = as_float_series(out["oat"])

    for pack_id in (1, 2):
        copy_numeric(f"bat_{pack_id}_current", f"bat {pack_id} current")
        copy_numeric(f"bat_{pack_id}_voltage", f"bat {pack_id} voltage")
        copy_numeric(f"bat_{pack_id}_soc", f"bat {pack_id} soc")
        copy_numeric(f"bat_{pack_id}_temp_min", f"bat {pack_id} min cell temp")
        copy_numeric(f"bat_{pack_id}_temp_max", f"bat {pack_id} max cell temp")
        copy_numeric(f"bat_{pack_id}_temp_avg", f"bat {pack_id} avg cell temp")
        copy_numeric(f"bat_{pack_id}_cell_v_min", f"bat {pack_id} min cell volt")
        copy_numeric(f"bat_{pack_id}_cell_v_max", f"bat {pack_id} max cell volt")

    out["source_pack_id"] = pd.Series(pd.array([pack_id_hint] * len(out), dtype="Int64"))
    if pack_id_hint in (1, 2):
        p = pack_id_hint
        copy_numeric("pack_current", f"bat {p} current")
        copy_numeric("pack_voltage", f"bat {p} voltage")
        copy_numeric("pack_soc", f"bat {p} soc")
        copy_numeric("pack_temp_min", f"bat {p} min cell temp")
        copy_numeric("pack_temp_max", f"bat {p} max cell temp")
        copy_numeric("pack_temp_avg", f"bat {p} avg cell temp")
        copy_numeric("pack_cell_v_min", f"bat {p} min cell volt")
        copy_numeric("pack_cell_v_max", f"bat {p} max cell volt")

    for col in FLOAT_CANONICAL_COLUMNS:
        if col not in out.columns:
            out[col] = pd.Series([float("nan")] * len(out), dtype="float64")
    for col in INT_CANONICAL_COLUMNS:
        if col not in out.columns:
            out[col] = pd.Series(pd.array([pd.NA] * len(out), dtype="Int64"))

    return out


def normalize_raw_chunk(frame: pd.DataFrame, raw_type_map: Dict[str, str], include_soh_columns: bool) -> pd.DataFrame:
    keep_cols = [col for col in frame.columns if not should_drop_column(col, include_soh_columns)]
    frame = frame[keep_cols].copy()
    for col in list(frame.columns):
        raw_kind = raw_type_map.get(col, RAW_STRING)
        if raw_kind == RAW_INT:
            frame[col] = as_int_series(frame[col])
        elif raw_kind == RAW_FLOAT:
            frame[col] = as_float_series(frame[col])
        else:
            frame[col] = as_string_series(frame[col])
    return frame


def build_arrow_schema(output_columns: Sequence[str], raw_type_map: Dict[str, str]) -> pa.Schema:
    fields: list[pa.Field] = []
    for col in output_columns:
        if col in raw_type_map:
            raw_kind = raw_type_map[col]
            if raw_kind == RAW_INT:
                fields.append(pa.field(col, pa.int64()))
            elif raw_kind == RAW_FLOAT:
                fields.append(pa.field(col, pa.float64()))
            else:
                fields.append(pa.field(col, pa.large_string()))
        elif col in STRING_META_COLUMNS:
            fields.append(pa.field(col, pa.large_string()))
        elif col in INT_META_COLUMNS or col in INT_CANONICAL_COLUMNS:
            fields.append(pa.field(col, pa.int64()))
        elif col in DATETIME_META_COLUMNS:
            fields.append(pa.field(col, pa.timestamp("ns")))
        elif col in FLOAT_CANONICAL_COLUMNS:
            fields.append(pa.field(col, pa.float64()))
        else:
            fields.append(pa.field(col, pa.large_string()))
    return pa.schema(fields)


def write_timeseries_parquet(
    event_dirs: Sequence[Path],
    timeseries_out: Path,
    include_warns: bool,
    include_soh_columns: bool,
    manifest_lookup: Dict[Path, Dict[str, Any]],
    chunk_rows: int,
    show_progress: bool,
) -> tuple[int, int]:
    raw_columns = collect_raw_columns(event_dirs, include_warns, include_soh_columns)
    output_columns = collect_output_columns(raw_columns)
    raw_type_map = infer_raw_column_types(event_dirs, raw_columns, include_warns, chunk_rows, show_progress)
    schema = build_arrow_schema(output_columns, raw_type_map)
    writer: Optional[pq.ParquetWriter] = None
    row_count = 0

    progress = SimpleProgressBar(len(event_dirs), "Writing parquet", enabled=show_progress)

    try:
        for event_dir in event_dirs:
            meta_record = manifest_lookup[event_dir]
            for csv_path in list_event_csv_paths(event_dir, include_warns):
                for chunk in iter_csv_chunks(csv_path, chunk_rows, dtype=str):
                    chunk = normalize_raw_chunk(chunk, raw_type_map, include_soh_columns)
                    meta_df = build_meta_frame(meta_record, csv_path, len(chunk))
                    chunk = pd.concat([chunk.reset_index(drop=True), meta_df], axis=1)
                    chunk = add_canonical_columns(chunk, pack_id_from_name(csv_path.name))
                    chunk = chunk.reindex(columns=output_columns)
                    table = pa.Table.from_pandas(chunk, schema=schema, preserve_index=False, safe=False)
                    if writer is None:
                        writer = pq.ParquetWriter(timeseries_out, schema)
                    writer.write_table(table)
                    row_count += len(chunk)
            progress.update(detail=event_dir.name)
    finally:
        progress.close()
        if writer is not None:
            writer.close()

    if writer is None:
        empty_df = pd.DataFrame(columns=output_columns)
        empty_df.to_parquet(timeseries_out, index=False)

    return row_count, len(output_columns)


def main() -> int:
    args = parse_args()
    raw_root = Path(args.raw_root)
    manifest_out = Path(args.manifest_out)
    timeseries_out = Path(args.timeseries_out)

    if not raw_root.exists():
        raise SystemExit(f"Raw root not found: {raw_root}")

    event_dirs: list[Path] = []
    manifest_rows: list[Dict[str, Any]] = []
    manifest_lookup: Dict[Path, Dict[str, Any]] = {}

    for idx, event_dir in enumerate(iter_event_dirs(raw_root), start=1):
        if args.max_events > 0 and idx > args.max_events:
            break
        meta = load_json(event_dir / "event_metadata.json")
        meta_record = base_event_record(meta, event_dir)
        manifest_rows.append(meta_record)
        manifest_lookup[event_dir] = meta_record
        event_dirs.append(event_dir)

    manifest_df = pd.DataFrame(manifest_rows)
    if not manifest_df.empty:
        manifest_df = manifest_df.sort_values(["plane_id", "event_datetime", "flight_id"], na_position="last").reset_index(drop=True)
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_df.to_parquet(manifest_out, index=False)

    timeseries_out.parent.mkdir(parents=True, exist_ok=True)
    if timeseries_out.exists():
        timeseries_out.unlink()
    timeseries_rows, timeseries_columns = write_timeseries_parquet(
        event_dirs=event_dirs,
        timeseries_out=timeseries_out,
        include_warns=args.include_warns,
        include_soh_columns=args.include_soh_columns,
        manifest_lookup=manifest_lookup,
        chunk_rows=args.chunk_rows,
        show_progress=args.progress,
    )

    print(json.dumps(
        {
            "raw_root": str(raw_root.resolve()),
            "manifest_out": str(manifest_out.resolve()),
            "timeseries_out": str(timeseries_out.resolve()),
            "event_count": int(len(manifest_df)),
            "timeseries_rows": int(timeseries_rows),
            "timeseries_columns": int(timeseries_columns),
            "chunk_rows": int(args.chunk_rows),
        },
        indent=2,
        default=str,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
