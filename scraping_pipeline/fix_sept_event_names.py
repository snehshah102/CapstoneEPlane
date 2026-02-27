#!/usr/bin/env python3
"""Repair legacy Event_Sept_* folder names and metadata.

This script renames only legacy folders whose names start with `Event_Sept_` to the
current canonical format `Event_YYYY-MM-DD_HHMM_<flight_id>`, then updates:
- event_metadata.json
- optional matching raw_zips event folder
- data/processed/scrape_manifest.csv

Example:
  python scraping_pipeline/fix_sept_event_names.py --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scraping_pipeline.pipistrel_scraper import build_event_dir_name

PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_RAW_CSV_ROOT = PROJECT_ROOT / "data" / "raw_csv" / "by_plane"
DEFAULT_RAW_ZIP_ROOT = PROJECT_ROOT / "data" / "raw_zips" / "by_plane"
DEFAULT_MANIFEST_CSV = PROJECT_ROOT / "data" / "processed" / "scrape_manifest.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fix legacy Event_Sept_* folder names and metadata.")
    parser.add_argument("--raw-csv-root", default=str(DEFAULT_RAW_CSV_ROOT), help="Root of raw_csv/by_plane.")
    parser.add_argument("--raw-zip-root", default=str(DEFAULT_RAW_ZIP_ROOT), help="Root of raw_zips/by_plane.")
    parser.add_argument("--manifest-csv", default=str(DEFAULT_MANIFEST_CSV), help="Optional scrape_manifest.csv path.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Without this flag, do a dry-run.")
    return parser.parse_args()


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def load_manifest_rows(path: Path) -> tuple[list[str], list[Dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    return fieldnames, rows


def save_manifest_rows(path: Path, fieldnames: list[str], rows: list[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def replace_prefix(value: Any, old: Path, new: Path) -> Any:
    if not isinstance(value, str):
        return value
    old_str = str(old.resolve())
    new_str = str(new.resolve())
    return value.replace(old_str, new_str)


def update_metadata_payload(meta: Dict[str, Any], old_csv_dir: Path, new_csv_dir: Path, old_zip_dir: Path | None, new_zip_dir: Path | None, new_name: str) -> Dict[str, Any]:
    updated = dict(meta)
    updated["event_dir_name"] = new_name
    updated["raw_csv_dir"] = str(new_csv_dir.resolve())
    updated["metadata_path"] = str((new_csv_dir / "event_metadata.json").resolve())

    note_txt = new_csv_dir / "note.txt"
    updated["note_txt_path"] = str(note_txt.resolve()) if note_txt.exists() or str(meta.get("note_txt_path", "")).strip() else ""

    if isinstance(updated.get("csv_zip_path"), str) and old_zip_dir is not None and new_zip_dir is not None:
        updated["csv_zip_path"] = updated["csv_zip_path"].replace(str(old_zip_dir.resolve()), str(new_zip_dir.resolve()))

    if isinstance(updated.get("csv_files_detail"), list):
        new_details = []
        for item in updated["csv_files_detail"]:
            new_item = dict(item)
            if isinstance(new_item.get("csv_path"), str):
                new_item["csv_path"] = new_item["csv_path"].replace(str(old_csv_dir.resolve()), str(new_csv_dir.resolve()))
            new_details.append(new_item)
        updated["csv_files_detail"] = new_details

    for key in ["metadata_path", "note_txt_path", "raw_csv_dir"]:
        if isinstance(updated.get(key), str):
            updated[key] = updated[key].replace(str(old_csv_dir.resolve()), str(new_csv_dir.resolve()))

    return updated


def main() -> int:
    args = parse_args()
    raw_csv_root = Path(args.raw_csv_root)
    raw_zip_root = Path(args.raw_zip_root)
    manifest_csv = Path(args.manifest_csv)

    if not raw_csv_root.exists():
        raise SystemExit(f"Raw CSV root not found: {raw_csv_root}")

    sept_dirs = sorted(p for p in raw_csv_root.rglob("Event_Sept_*") if p.is_dir())
    if not sept_dirs:
        print("No Event_Sept_* folders found.")
        return 0

    manifest_fieldnames: list[str] = []
    manifest_rows: list[Dict[str, str]] = []
    if manifest_csv.exists():
        manifest_fieldnames, manifest_rows = load_manifest_rows(manifest_csv)

    planned: List[Dict[str, str]] = []

    for old_csv_dir in sept_dirs:
        meta_path = old_csv_dir / "event_metadata.json"
        if not meta_path.exists():
            continue
        meta = load_json(meta_path)
        flight_id = int(meta["flight_id"])
        detail_date = str(meta.get("detail_date") or meta.get("list_date") or "")
        new_name = build_event_dir_name(detail_date, flight_id)
        if new_name == old_csv_dir.name:
            continue

        new_csv_dir = old_csv_dir.parent / new_name
        plane_id = old_csv_dir.parent.name
        old_zip_dir = raw_zip_root / plane_id / old_csv_dir.name
        new_zip_dir = raw_zip_root / plane_id / new_name

        planned.append(
            {
                "flight_id": str(flight_id),
                "old_csv_dir": str(old_csv_dir),
                "new_csv_dir": str(new_csv_dir),
                "old_zip_dir": str(old_zip_dir) if old_zip_dir.exists() else "",
                "new_zip_dir": str(new_zip_dir),
            }
        )

        if not args.apply:
            continue

        if new_csv_dir.exists():
            raise SystemExit(f"Target CSV dir already exists: {new_csv_dir}")
        if old_zip_dir.exists() and new_zip_dir.exists():
            raise SystemExit(f"Target ZIP dir already exists: {new_zip_dir}")

        if old_zip_dir.exists():
            new_zip_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_zip_dir), str(new_zip_dir))
        else:
            new_zip_dir = None

        shutil.move(str(old_csv_dir), str(new_csv_dir))

        updated_meta = update_metadata_payload(
            meta=meta,
            old_csv_dir=old_csv_dir,
            new_csv_dir=new_csv_dir,
            old_zip_dir=old_zip_dir if old_zip_dir.exists() or (raw_zip_root / plane_id / old_csv_dir.name).exists() else old_zip_dir,
            new_zip_dir=new_zip_dir,
            new_name=new_name,
        )
        write_json(new_csv_dir / "event_metadata.json", updated_meta)

        if manifest_rows:
            for row in manifest_rows:
                try:
                    row_flight_id = int(row.get("flight_id", ""))
                except ValueError:
                    continue
                if row_flight_id != flight_id:
                    continue
                row["event_dir_name"] = new_name
                row["raw_csv_dir"] = str(new_csv_dir.resolve())
                row["metadata_path"] = str((new_csv_dir / "event_metadata.json").resolve())
                note_txt = new_csv_dir / "note.txt"
                row["note_txt_path"] = str(note_txt.resolve()) if note_txt.exists() else ""
                if new_zip_dir is not None and row.get("csv_zip_path"):
                    row["csv_zip_path"] = row["csv_zip_path"].replace(str(old_zip_dir.resolve()), str(new_zip_dir.resolve()))
                break

    if args.apply and manifest_rows and manifest_fieldnames:
        save_manifest_rows(manifest_csv, manifest_fieldnames, manifest_rows)

    print(json.dumps({
        "apply": bool(args.apply),
        "sept_dirs_found": len(sept_dirs),
        "renames_planned": planned,
    }, indent=2))
    if args.apply:
        print("Rebuild parquet outputs after this if you want processed paths updated:")
        print("  python scraping_pipeline/build_event_timeseries_parquet.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
