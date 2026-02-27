#!/usr/bin/env python3
"""Extract ZIP event bundles into directory-based CSV files.

Supports both layouts:
- data/raw_zips/by_plane/<plane_id>/<event_dir>/<bundle>.zip
- data/raw_zips/by_plane/<plane_id>/<legacy_bundle>.zip

Output:
- data/raw_csv/by_plane/<plane_id>/<event_dir>/*.csv
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_ZIP_ROOT = PROJECT_ROOT / "data" / "raw_zips" / "by_plane"
DEFAULT_OUT_ROOT = PROJECT_ROOT / "data" / "raw_csv" / "by_plane"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract ZIP files into raw_csv by plane and event folder.")
    parser.add_argument("--zip-root", default=str(DEFAULT_ZIP_ROOT), help="Root folder containing plane-id folders with ZIP files.")
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT), help="Output root for extracted CSV files.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite CSV files if they already exist.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned extraction without writing files.")
    return parser.parse_args()


def safe_member_name(name: str) -> str:
    return Path(name).name


def iter_zip_files(zip_root: Path) -> list[Path]:
    return sorted(zip_root.rglob("*.zip"))


def event_output_dir(zip_root: Path, out_root: Path, zpath: Path) -> Path:
    rel = zpath.relative_to(zip_root)
    parts = rel.parts
    if len(parts) < 2:
        return out_root / zpath.stem
    plane_id = parts[0]
    if len(parts) == 2:
        return out_root / plane_id / zpath.stem
    return out_root / plane_id / parts[-2]


def maybe_copy_metadata(src_zip_event_dir: Path, out_event_dir: Path, dry_run: bool) -> int:
    copied = 0
    for name in ["event_metadata.json", "note.txt"]:
        src = src_zip_event_dir / name
        dst = out_event_dir / name
        if not src.exists() or dst.exists():
            continue
        if dry_run:
            print(f"[dry-run] {src} -> {dst}")
            copied += 1
            continue
        out_event_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    return copied


def main() -> int:
    args = parse_args()
    zip_root = Path(args.zip_root)
    out_root = Path(args.out_root)

    if not zip_root.exists():
        raise SystemExit(f"ZIP root not found: {zip_root}")

    zip_files = iter_zip_files(zip_root)
    if not zip_files:
        print(f"No ZIP files found under: {zip_root.resolve()}")
        return 0

    extracted = 0
    skipped = 0
    archives = 0
    metadata_copied = 0

    for zpath in zip_files:
        archives += 1
        event_dir = event_output_dir(zip_root, out_root, zpath)
        metadata_copied += maybe_copy_metadata(zpath.parent, event_dir, args.dry_run)

        with zipfile.ZipFile(zpath) as zf:
            members = [m for m in zf.infolist() if (not m.is_dir()) and m.filename.lower().endswith(".csv")]
            for member in members:
                out_name = safe_member_name(member.filename)
                if not out_name:
                    continue
                out_path = event_dir / out_name
                if out_path.exists() and not args.overwrite:
                    skipped += 1
                    continue
                if args.dry_run:
                    print(f"[dry-run] {zpath} -> {out_path}")
                    extracted += 1
                    continue
                event_dir.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, out_path.open("wb") as dst:
                    dst.write(src.read())
                extracted += 1

    print(f"ZIP archives scanned: {archives}")
    print(f"CSV files extracted: {extracted}")
    print(f"CSV files skipped: {skipped}")
    print(f"Metadata sidecars copied: {metadata_copied}")
    print(f"Output root: {out_root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
